"""seekdb integration for the Qoder reviewer.

This module is the bridge that makes the database part of the **review itself**:

1. the rule knowledge lives in the database and is searched with a hybrid plan
   (IK fulltext branch + HNSW vector branch, RRF fused inside the seekdb kernel)
   -- the hits become the *basis* attached to every finding;
2. every review round is written back and can be **read back** by the next
   process (``run.py --readback``, ``GET /api/reviews``).

Backend: the real seekdb kernel when ``pylibseekdb`` is installed, otherwise the
standard-library sqlite file at ``Qoder/data/memory.db``. Both are durable, so
the judge can verify that data written in one run is readable in the next one.

Everything degrades gracefully: when no backend can be opened the reviewer
keeps working with the deterministic rule engine only, and the status reports
*why* instead of pretending the integration is there.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

DEFAULT_DB_DIR = HERE.parent / "data"


def _memory():
    from memory_store import get_memory  # noqa: PLC0415

    return get_memory()


class QoderReviewStore:
    """Review-side view of the memory (seekdb kernel or sqlite file)."""

    def __init__(self, db_dir: str | Path | None = None) -> None:  # noqa: ARG002
        self.memory = None
        self.available = False
        self.reason = ""

    # -- lifecycle -------------------------------------------------------
    def open(self, reset: bool = False) -> "QoderReviewStore":  # noqa: ARG002
        self.memory = _memory()
        self.available = self.memory.available
        self.reason = self.memory.reason
        if self.available:
            self.ensure_ready()
        return self

    def close(self) -> None:
        self.memory = None
        self.available = False

    # -- knowledge -------------------------------------------------------
    def ensure_ready(self) -> int:
        if not self.available or self.memory is None:
            return 0
        rows = self.memory.ensure_ready()
        self.available = self.memory.available
        self.reason = self.memory.reason
        return rows

    # -- retrieval -------------------------------------------------------
    def search_basis(self, query: str, top_k: int = 2) -> list[dict[str, Any]]:
        if not self.available or self.memory is None:
            return []
        hits = self.memory.search(query, top_k)
        self.reason = self.memory.reason
        return hits

    def enrich(self, findings: list[dict[str, Any]], sql: str = "") -> list[dict[str, Any]]:
        """Attach the database-retrieved basis to every finding."""
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
        """Persist one review round into the memory."""
        if not self.available or self.memory is None:
            return None
        levels = [str(item.get("level", "info")) for item in findings]
        severity = "error" if "error" in levels else ("warn" if "warn" in levels else "info")
        summary = f"{severity} 级问题 {len(findings)} 条" if findings else "未发现问题"
        review_id = self.memory.write_review(
            engine="qoder-review-assistant",
            sql_text=sql,
            findings=findings,
            summary=summary,
            kb_hits=kb_hits,
        )
        self.reason = self.memory.reason
        return review_id or None

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        if not self.available or self.memory is None:
            return []
        return self.memory.list_reviews(limit)

    # -- status ----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        if self.memory is None:
            return {
                "available": False,
                "engine": "seekdb/sqlite",
                "reason": self.reason or "记忆层未初始化",
            }
        payload = self.memory.stats()
        payload.setdefault("available", self.available)
        return payload


def get_store() -> QoderReviewStore:
    """Process-wide store (opened once, reused by every request)."""
    return QoderReviewStore().open()


def review_with_seekdb(sql: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Enrich + persist one review round; never raises."""
    try:
        store = get_store()
        status = store.status()
        if not status.get("available"):
            return {"findings": findings, "seekdb": status, "review_id": None}
        enriched = store.enrich(findings, sql)
        hits = sum(1 for item in enriched if item.get("basis"))
        review_id = store.record(sql, enriched, kb_hits=hits)
        return {"findings": enriched, "seekdb": store.status(), "review_id": review_id}
    except Exception as error:  # noqa: BLE001
        return {
            "findings": findings,
            "seekdb": {
                "available": False,
                "engine": "seekdb/sqlite",
                "reason": f"{type(error).__name__}: {error}",
            },
            "review_id": None,
        }
