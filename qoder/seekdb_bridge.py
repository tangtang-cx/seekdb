"""seekdb bridge for the Qoder track.

The review assistant talks to a **real seekdb** through the shared knowledge
service (``dify/seekdb_service/serve.py``):

* ``/search``  -> hybrid retrieval (bge-small-zh vectors + IK fulltext + RRF,
  fused inside the seekdb kernel) to pull the "医书" passages that justify the review;
* ``/reviews`` -> the review rounds are written **into seekdb** as well, so the
  storage side of the integration is real and can be queried back.

Every call degrades gracefully: if the service is not running the assistant
still works with the local rule engine only.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8848"


def _post(base_url: str, path: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get(base_url: str, path: str, timeout: int = 15) -> dict[str, Any]:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}{path}", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def health(base_url: str = DEFAULT_BASE_URL) -> dict[str, Any]:
    """Return the service status, or an error dict when it is unreachable."""
    try:
        return _get(base_url, "/health")
    except Exception as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}


def search_knowledge(query: str, base_url: str = DEFAULT_BASE_URL, top_k: int = 3) -> list[dict[str, Any]]:
    """Hybrid (vector + fulltext, RRF) retrieval from seekdb."""
    payload = _post(base_url, "/search", {"query": query, "top_k": top_k, "mode": "hybrid"})
    return payload.get("hits", [])


def search_context(query: str, base_url: str = DEFAULT_BASE_URL, top_k: int = 3) -> str:
    payload = _post(base_url, "/search", {"query": query, "top_k": top_k, "mode": "hybrid"})
    return payload.get("context", "")


def save_review(
    *,
    sql: str,
    findings: list[dict[str, Any]],
    engine: str,
    summary: str = "",
    kb_hits: int = 0,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """Write one review round into seekdb."""
    payload = _post(
        base_url,
        "/reviews",
        {"sql": sql, "findings": findings, "engine": engine, "summary": summary, "kb_hits": kb_hits},
    )
    return payload


def list_reviews(base_url: str = DEFAULT_BASE_URL, limit: int = 20) -> list[dict[str, Any]]:
    payload = _get(base_url, "/reviews")
    return payload.get("reviews", [])[:limit]
