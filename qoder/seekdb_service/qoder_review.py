"""seekdb integration for the Qoder reviewer (embedded kernel, real read + write).

This module is the bridge that makes seekdb part of the **review itself**:

1. the rule knowledge (``qoder_rule_knowledge``) lives in seekdb and is searched
   with a hybrid plan (IK fulltext branch + HNSW vector branch, fused by seekdb's
   RRF ranker) -- the hits become the *basis* attached to every finding;
2. every review round is written back into seekdb (``qoder_review_log``), so the
   storage side of the integration is real and can be queried back.

Everything degrades gracefully: when the ``pylibseekdb`` wheel is not installed
the reviewer keeps working with the deterministic rule engine only, and the
status reports *why* instead of pretending the integration is there.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

DEFAULT_DB_DIR = HERE / ".data" / "qoder-seekdb"

_LOCK = threading.RLock()
_STORE: "QoderReviewStore | None" = None


def _embedder() -> Any:
    """The real bge model when its weights are present, else the hashing fallback."""
    from embedder import Embedder, HashingEmbedder  # noqa: PLC0415

    try:
        return Embedder.get()
    except Exception:  # noqa: BLE001  (missing weights -> deterministic fallback)
        return HashingEmbedder()


class QoderReviewStore:
    """Embedded seekdb store holding the rule knowledge and the review history."""

    def __init__(self, db_dir: str | Path | None = None) -> None:
        self.db_dir = Path(db_dir or os.environ.get("SEEKDB_PATH", DEFAULT_DB_DIR))
        self.store: Any = None
        self.embedder: Any = None
        self.available = False
        self.reason = ""
        self.mode = "embedded"

    # -- lifecycle -------------------------------------------------------
    def open(self, reset: bool = False) -> "QoderReviewStore":
        try:
            from seekdb_store import SeekdbStore  # noqa: PLC0415
        except Exception as error:  # noqa: BLE001
            self.reason = f"seekdb_store 导入失败: {type(error).__name__}: {error}"
            return self
        try:
            self.store = SeekdbStore(str(self.db_dir))
            self.store.open(reset=reset)
            self.mode = self.store.mode
            self.available = True
            self.reason = ""
        except Exception as error:  # noqa: BLE001
            self.reason = f"seekdb 内核不可用: {type(error).__name__}: {error}"
            self.available = False
            return self
        self.embedder = _embedder()
        self.ensure_ready()
        return self

    def close(self) -> None:
        if self.store is not None:
            try:
                self.store.close()
            except Exception:  # noqa: BLE001
                pass
        self.store = None
        self.available = False

    # -- knowledge -------------------------------------------------------
    def ensure_ready(self) -> int:
        """Ingest the rule knowledge once; returns the number of stored rows."""
        if not self.available or self.store is None:
            return 0
        try:
            if self.store.count() > 0:
                return self.store.count()
            from knowledge import build_documents  # noqa: PLC0415

            documents = build_documents()
            texts = [item["text"] for item in documents]
            vectors = self.embedder.embed(texts)
            rows = []
            for item, vector in zip(documents, vectors):
                rows.append(
                    {
                        "id": item["id"],
                        "text": item["text"],
                        "metadata": item["metadata"],
                        "embedding": vector,
                    }
                )
            return self.store.upsert(rows)
        except Exception as error:  # noqa: BLE001
            self.reason = f"规则知识入库失败: {type(error).__name__}: {error}"
            self.available = False
            return 0

    # -- retrieval -------------------------------------------------------
    def search_basis(self, query: str, top_k: int = 2) -> list[dict[str, Any]]:
        """Hybrid (fulltext + vector) search executed inside the seekdb kernel."""
        if not self.available or self.store is None:
            return []
        try:
            vector = self.embedder.embed_one(query)
            hits = self.store.search(query, vector, top_k, "hybrid")
            return hits
        except Exception as error:  # noqa: BLE001
            self.reason = f"检索失败: {type(error).__name__}: {error}"
            return []

    def enrich(self, findings: list[dict[str, Any]], sql: str = "") -> list[dict[str, Any]]:
        """Attach the seekdb-retrieved basis to every finding."""
        if not self.available or not findings:
            return findings
        cache: dict[str, list[dict[str, Any]]] = {}
        for finding in findings:
            rule_id = str(finding.get("id", ""))
            title = str(finding.get("title", ""))
            query = f"{rule_id} {title} 判定依据与修复建议"
            if rule_id not in cache:
                cache[rule_id] = self.search_basis(query, top_k=1)
            hits = cache[rule_id]
            if hits:
                hit = hits[0]
                finding["basis"] = {
                    "rule_id": rule_id,
                    "source": hit.get("source", ""),
                    "title": hit.get("title", ""),
                    "score": hit.get("score"),
                    "excerpt": (hit.get("text", "") or "")[:220],
                }
            else:
                finding["basis"] = None
        return findings

    # -- storage ---------------------------------------------------------
    def record(self, sql: str, findings: list[dict[str, Any]], kb_hits: int = 0) -> str | None:
        """Persist one review round into seekdb."""
        if not self.available or self.store is None:
            return None
        try:
            levels = [str(item.get("level", "info")) for item in findings]
            severity = "error" if "error" in levels else ("warn" if "warn" in levels else "info")
            summary = (
                f"{severity} 级问题 {len(findings)} 条"
                if findings
                else "未发现问题"
            )
            return self.store.write_review(
                engine="qoder-review-assistant",
                sql_text=sql,
                findings=findings,
                summary=summary,
                kb_hits=kb_hits,
            )
        except Exception as error:  # noqa: BLE001
            self.reason = f"审查历史写入失败: {type(error).__name__}: {error}"
            return None

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        if not self.available or self.store is None:
            return []
        try:
            return self.store.list_reviews(limit)
        except Exception:  # noqa: BLE001
            return []

    # -- status ----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "available": self.available,
            "engine": "seekdb",
            "mode": self.mode,
            "reason": self.reason,
        }
        if self.available and self.store is not None:
            try:
                payload["rule_knowledge_rows"] = self.store.count()
                payload["review_log_rows"] = self.store.review_count()
            except Exception as error:  # noqa: BLE001
                payload["reason"] = f"{type(error).__name__}: {error}"
        if self.embedder is not None:
            payload["embedding"] = {
                "model": "bge-small-zh-v1.5 (INT8 ONNX)"
                if not getattr(self.embedder, "is_fallback", False)
                else "deterministic hashing fallback",
                "dim": 512,
                "fallback": bool(getattr(self.embedder, "is_fallback", False)),
            }
        return payload


def get_store() -> QoderReviewStore:
    """Process-wide store (opened once, reused by every request)."""
    global _STORE
    with _LOCK:
        if _STORE is None:
            _STORE = QoderReviewStore().open()
        return _STORE


def review_with_seekdb(sql: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Enrich + persist one review round; never raises."""
    store = get_store()
    status = store.status()
    if not status.get("available"):
        return {"findings": findings, "seekdb": status, "review_id": None}
    enriched = store.enrich(findings, sql)
    hits = sum(1 for item in enriched if item.get("basis"))
    review_id = store.record(sql, enriched, kb_hits=hits)
    status = store.status()
    return {"findings": enriched, "seekdb": status, "review_id": review_id}
