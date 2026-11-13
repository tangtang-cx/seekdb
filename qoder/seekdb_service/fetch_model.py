#!/usr/bin/env python3
"""Fetch the pinned bge-small-zh-v1.5 model (INT8) used by the seekdb service.

The weights are too large for git, so they are downloaded once from a Hugging
Face mirror. The same pinned revision is used by the StepFun browser app
(``stepfun/scripts/fetch-model.mjs``), so both projects embed identical vectors.

    python dify/seekdb_service/fetch_model.py
    MODEL_HOST=https://hf-mirror.com python dify/seekdb_service/fetch_model.py
"""

from __future__ import annotations

import os
import ssl
import sys
import urllib.request
from pathlib import Path

REPO = "Xenova/bge-small-zh-v1.5"
REVISION = "75c43b069aac4d136ba6bc1122f995fedcfd2781"
HOST = os.environ.get("MODEL_HOST", "https://hf-mirror.com")
TARGET = Path(__file__).resolve().parents[2] / "stepfun" / "public" / "models" / "bge-small-zh-v1.5"

FILES = [
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "onnx/model_int8.onnx",
]


def download(relative: str) -> None:
    target = TARGET / relative
    if target.exists() and target.stat().st_size > 0:
        print(f"skip  {relative} ({target.stat().st_size} bytes)")
        return
    url = f"{HOST}/{REPO}/resolve/{REVISION}/{relative}"
    print(f"fetch {relative}")
    request = urllib.request.Request(url, headers={"User-Agent": "seekdb-service"})
    with urllib.request.urlopen(request, timeout=180, context=ssl.create_default_context()) as response:
        data = response.read()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"saved {relative} ({len(data)} bytes)")


def main() -> int:
    for name in FILES:
        try:
            download(name)
        except Exception as error:
            print(f"FAIL {name}: {error}", file=sys.stderr)
            return 1
    print("model ready:", TARGET)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
