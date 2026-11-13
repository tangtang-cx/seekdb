#!/usr/bin/env python3
"""Command line demo of the Dify project: real seekdb + real retrieval.

    python run.py                       # one query against the seekdb knowledge base
    python run.py "你的问题"             # custom query
    python run.py --check               # dependency / service health check only

Exit code 0 means: the seekdb kernel is up, the knowledge base is indexed and
the hybrid retrieval (vector + fulltext, RRF inside seekdb) returned results.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "seekdb_service"))

DEFAULT_QUERY = "HNSW 向量索引的建表语句是什么？"


def main() -> int:
    parser = argparse.ArgumentParser(description="Dify x seekdb demo")
    parser.add_argument("query", nargs="?", default=DEFAULT_QUERY)
    parser.add_argument("--check", action="store_true", help="only print the health check")
    parser.add_argument("--url", default="http://127.0.0.1:8848")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")

    from auto_start import ensure_service

    print("== 1. 启动/连接 seekdb 知识服务 ==", flush=True)
    started = time.time()
    health = ensure_service(args.url)
    if not health.get("ok"):
        print(f"FAIL: seekdb service not ready: {health.get('error')}")
        return 1
    print(
        f"   ok: mode={health.get('mode')} chunks={health.get('chunks')} "
        f"dim={health.get('embedding_dim')} ({int((time.time() - started))}s)"
    )

    if args.check:
        print("\nPASS: dependencies and the seekdb service are fine")
        return 0

    print(f"\n== 2. 混合检索（向量 + 全文 + RRF，融合在 seekdb 内核内完成）: {args.query} ==", flush=True)
    import urllib.request

    body = json.dumps({"query": args.query, "top_k": 3, "mode": "hybrid"}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{args.url.rstrip('/')}/search",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))

    hits = payload.get("hits", [])
    print(f"   engine={payload.get('engine')} took_ms={payload.get('took_ms')} hits={len(hits)}")
    for index, hit in enumerate(hits, start=1):
        print(f"   [{index}] {hit.get('title')}  ({hit.get('source')})")
        print(f"       {(hit.get('text') or '')[:120]}".replace("\n", " "))
    if not hits:
        print("FAIL: no hits returned")
        return 1

    print("\n== 3. 写入一条审查记录到 seekdb（存储侧） ==", flush=True)
    body = json.dumps(
        {
            "sql": args.query,
            "findings": [{"level": "info", "title": "demo record"}],
            "engine": "run.py",
            "summary": "run.py demo",
            "kb_hits": len(hits),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{args.url.rstrip('/')}/reviews",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        saved = json.loads(response.read().decode("utf-8"))
    print(f"   ok: id={saved.get('id')} total_reviews={saved.get('reviews')}")

    print("\nPASS: Dify x seekdb project runs end to end (real seekdb kernel, real local embeddings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
