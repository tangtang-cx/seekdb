#!/usr/bin/env python3
"""Standalone seekdb integration self-check (runs in its own process).

Executed by ``run.py`` as a child process with a hard timeout, so a broken or
hanging kernel can never block the main self-check.

Prints one JSON line on stdout:

    {"ok": true, "rows": 15, "hits": 2, "reviews": 1, "detail": "..."}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))


def main() -> int:
    from qoder_review import QoderReviewStore  # noqa: PLC0415

    store = QoderReviewStore(HERE / ".data" / "selfcheck-seekdb")
    store.open(reset=True)
    if not store.available:
        print(json.dumps({"ok": False, "reason": store.reason}, ensure_ascii=False))
        return 1

    rows = store.ensure_ready()
    hits = store.search_basis("深分页 OFFSET 太大怎么办？", top_k=2)
    store.record(
        "SELECT id FROM orders ORDER BY id LIMIT 20, 200000;",
        [{"id": "OB-007", "level": "warn", "title": "深分页 OFFSET"}],
    )
    status = store.status()
    store.close()

    payload = {
        "ok": rows >= 15 and len(hits) >= 1 and int(status.get("review_log_rows", 0)) >= 1,
        "rows": rows,
        "hits": len(hits),
        "reviews": status.get("review_log_rows"),
        "embedding": status.get("embedding"),
        "detail": (
            f"规则知识 {rows} 条入库；混合检索命中 {len(hits)} 条；"
            f"审查历史 {status.get('review_log_rows')} 行写入"
        ),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
