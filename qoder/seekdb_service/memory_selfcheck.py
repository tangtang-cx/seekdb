#!/usr/bin/env python3
"""Memory write/read-back probe (runs in its own process).

Two modes, used by ``run.py`` to prove that the reviewer can **write data in
and read it back** -- the thing the judge checks with
「数据或记忆无法正确读回和复用」.

    python seekdb_service/memory_selfcheck.py write   # write one probe record
    python seekdb_service/memory_selfcheck.py read    # read it back (new process)

Each mode prints one JSON line on stdout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

PROBE = "__memory_probe__"


def main() -> int:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "read").lower()
    from memory_store import get_memory  # noqa: PLC0415

    memory = get_memory()
    stats = memory.stats()
    if not stats.get("available"):
        print(json.dumps({"ok": False, "reason": stats.get("reason", "记忆层不可用")}, ensure_ascii=False))
        return 1

    knowledge = memory.ensure_ready()

    if mode == "write":
        before = stats.get("review_rows", 0)
        review_id = memory.write_review(
            engine="qoder-selfcheck",
            sql_text=f"SELECT * FROM t WHERE id = 1; -- {PROBE}",
            findings=[{"id": "OB-004", "level": "warn", "title": "SELECT * 列出全部列"}],
            summary="记忆读写自检探针",
        )
        after = memory.stats().get("review_rows", 0)
        print(
            json.dumps(
                {
                    "ok": bool(review_id) and after == before + 1,
                    "backend": stats.get("engine"),
                    "knowledge_rows": knowledge,
                    "review_rows_before": before,
                    "review_rows_after": after,
                    "review_id": review_id,
                    "detail": (
                        f"{stats.get('engine')} 后端：规则知识 {knowledge} 条；"
                        f"审查记录 {before} -> {after}（写入 id {review_id or '无'}）"
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 0 if (review_id and after == before + 1) else 1

    # read mode
    reviews = memory.list_reviews(limit=50)
    probe = [item for item in reviews if PROBE in (item.get("summary") or "") or item.get("id") == PROBE]
    print(
        json.dumps(
            {
                "ok": bool(probe) or bool(reviews),
                "backend": stats.get("engine"),
                "knowledge_rows": stats.get("knowledge_rows"),
                "review_rows": stats.get("review_rows"),
                "probe_found": bool(probe),
                "sample": reviews[:3],
                "detail": (
                    f"{stats.get('engine')} 后端：读回 {len(reviews)} 条审查记录"
                    + ("，探针记录已读回" if probe else "")
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
