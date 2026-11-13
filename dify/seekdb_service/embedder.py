"""Local bge-small-zh-v1.5 embedding backend (ONNX Runtime, INT8).

The same model the StepFun task uses in the browser
(``stepfun/public/models/bge-small-zh-v1.5``) is loaded here on the server side
so that the Dify demo does not depend on any cloud inference API.

* tokenizer: ``tokenizer.json`` (HuggingFace tokenizers, Rust wheel)
* weights:   ``onnx/model_int8.onnx`` (22.8 MiB, static INT8 quantization)
* pooling:   CLS token + L2 normalisation -> 512-dim cosine vectors
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

try:  # optional: only needed for the real bge model
    import numpy as np
except Exception:  # pragma: no cover - numpy is optional
    np = None

try:  # optional: only needed for the real bge model
    import onnxruntime as ort
except Exception:  # pragma: no cover - onnxruntime is optional
    ort = None

DEFAULT_MODEL_DIR = Path(
    os.environ.get(
        "BGE_MODEL_DIR",
        Path(__file__).resolve().parents[2] / "stepfun" / "public" / "models" / "bge-small-zh-v1.5",
    )
)

EMBEDDING_DIM = 512


class Embedder:
    """Lazy, thread-safe singleton around the ONNX model.

    When the ONNX weights are not present (they are not committed to git), the
    factory falls back to :class:`HashingEmbedder` so that the whole pipeline
    (seekdb storage + vector retrieval + RRF fusion) keeps working instead of
    the service refusing to start.
    """

    _instance: "Embedder | HashingEmbedder | None" = None
    _lock = threading.Lock()

    def __init__(self, model_dir: Path | None = None) -> None:
        self.model_dir = Path(model_dir or DEFAULT_MODEL_DIR)
        onnx_path = self.model_dir / "onnx" / "model_int8.onnx"
        tokenizer_path = self.model_dir / "tokenizer.json"
        if not onnx_path.exists() or not tokenizer_path.exists():
            raise FileNotFoundError(
                f"model files missing under {self.model_dir} "
                "(expected onnx/model_int8.onnx and tokenizer.json); "
                "run `python dify/seekdb_service/fetch_model.py` to fetch them"
            )

        from tokenizers import Tokenizer

        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self.session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        self.max_length = 512
        self.is_fallback = False
        self._lock = threading.Lock()

    @classmethod
    def get(cls, model_dir: Path | None = None) -> "Embedder | HashingEmbedder":
        with cls._lock:
            if cls._instance is None:
                try:
                    cls._instance = cls(model_dir)
                except Exception as error:  # missing weights / missing onnxruntime
                    fallback = HashingEmbedder()
                    fallback.reason = str(error)
                    cls._instance = fallback
            return cls._instance

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into L2-normalised 512-dim vectors."""
        if not texts:
            return []
        encodings = [self.tokenizer.encode(text) for text in texts]
        width = min(self.max_length, max(len(enc.ids) for enc in encodings))

        input_ids = np.zeros((len(encodings), width), dtype=np.int64)
        attention_mask = np.zeros((len(encodings), width), dtype=np.int64)
        token_type_ids = np.zeros((len(encodings), width), dtype=np.int64)

        for row, enc in enumerate(encodings):
            ids = enc.ids[:width]
            input_ids[row, : len(ids)] = ids
            attention_mask[row, : len(ids)] = enc.attention_mask[:width]
            token_type_ids[row, : len(ids)] = enc.type_ids[:width] if enc.type_ids else 0

        outputs = self.session.run(
            ["last_hidden_state"],
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )
        hidden = outputs[0]

        vectors = []
        for row in range(hidden.shape[0]):
            mask = attention_mask[row].astype(np.float32)
            cls = hidden[row, 0]
            # mean pooling over non-padding tokens (CLS is included, matching bge)
            summed = (hidden[row] * mask[:, None]).sum(axis=0)
            count = max(float(mask.sum()), 1.0)
            pooled = cls + (summed - cls) / count if count > 1 else cls
            norm = float(np.linalg.norm(pooled))
            if norm > 0:
                pooled = pooled / norm
            vectors.append(pooled.astype(np.float32).tolist())
        return vectors

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class HashingEmbedder:
    """Deterministic fallback embedder (character n-gram hashing).

    It is *not* a neural model, but it produces stable, L2-normalised 512-dim
    vectors, so seekdb still stores real vectors, still builds the HNSW index
    and still fuses the vector and fulltext branches with RRF. The app shows a
    banner saying which mode is active.
    """

    is_fallback = True
    reason = "onnx weights not available"

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim
        self.model_dir = DEFAULT_MODEL_DIR

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into L2-normalised 512-dim vectors (pure Python)."""
        vectors = []
        for text in texts:
            vec = [0.0] * self.dim
            grams = list(text) + [text[i : i + 2] for i in range(len(text) - 1)]
            for gram in grams:
                digest = hashlib.sha256(gram.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % self.dim
                vec[index] += 1.0 if digest[4] % 2 == 0 else -1.0
            norm = sum(value * value for value in vec) ** 0.5
            if norm > 0:
                vec = [value / norm for value in vec]
            vectors.append(vec)
        return vectors

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]



def cosine(a: list[float], b: list[float]) -> float:
    return float(np.dot(np.asarray(a), np.asarray(b)))


if __name__ == "__main__":  # quick self-check
    emb = Embedder.get()
    vectors = emb.embed(
        [
            "HNSW 是一种分层可导航小世界图索引，用于近似最近邻搜索。",
            "向量索引可以用 HNSW 来实现近似最近邻检索。",
            "今天中午吃什么？红烧肉真香。",
        ]
    )
    print(json.dumps({"dim": len(vectors[0]), "cos_related": cosine(vectors[0], vectors[1]),
                      "cos_unrelated": cosine(vectors[0], vectors[2])}, ensure_ascii=False, indent=2))
