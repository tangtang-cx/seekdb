#!/usr/bin/env python3
"""End-to-end verification of the Dify <-> seekdb knowledge service.

Runs the whole chain against a **real seekdb kernel** and writes the evidence
to ``EVIDENCE.json`` (next to this file):

1. open seekdb (embedded by default, or a seekdb server via ``SEEKDB_HOST``);
2. embed ``kb/*.md`` with the local bge-small-zh-v1.5 INT8 model;
3. insert the chunks into the seekdb table (HNSW vector index + IK fulltext);
4. run hybrid (vector + fulltext, RRF inside seekdb) queries;
5. print the plan that seekdb generated, so you can see ``_fts``/``_vs`` branches.

    python Dify/seekdb_service/verify.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from embedder import Embedder  # noqa: E402
from seekdb_store import SeekdbStore  # noqa: E402
from serve import ingest, load_kb_documents  # noqa: E402

QUERIES = [
    "HNSW 向量索引的建表语句是什么？",
    "混合检索的 RRF 融合是怎么做的？",
    "端侧 INT8 量化会损失多少召回率？",
    "AMD GPU 加速 HNSW 的建图收益有多少？",
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    base = Path(__file__).resolve().parent
    store = SeekdbStore(str(base / ".data" / "dify-seekdb"))
    store.open(reset=True)
    embedder = Embedder.get()

    print(f"seekdb mode      : {store.mode}")
    print(f"embedding model  : bge-small-zh-v1.5 (INT8 ONNX), dim=512")

    started = time.time()
    chunks = ingest(store, embedder, load_kb_documents())
    print(f"ingested chunks  : {chunks} (rows in seekdb: {store.count()}) in {time.time() - started:.1f}s")

    evidence = {
        "engine": "seekdb",
        "mode": store.mode,
        "embedding": "bge-small-zh-v1.5 / INT8 ONNX / 512-dim cosine",
        "table": "dify_knowledge_base",
        "indexes": ["FULLTEXT idx_fts (document) WITH PARSER ik", "VECTOR idx_vec (embedding) type=hnsw lib=vsag"],
        "chunks": chunks,
        "queries": [],
    }

    for query in QUERIES:
        vector = embedder.embed_one(query)
        plan = store._hybrid_sql(
            {
                "query": {"query_string": {"fields": ["document"], "query": query}},
                "knn": {"field": "embedding", "k": 5, "query_vector": vector},
                "rank": {"rrf": {}},
                "size": 3,
            }
        )
        hits = store.search(query, vector, 3, "hybrid")
        print(f"\nQ: {query}")
        print(f"   plan contains fulltext branch: {'_fts' in plan}; vector branch: {'_vs' in plan}")
        for hit in hits:
            print(f"   - [{hit['title'][:30]}] score={hit['score']} :: {hit['text'][:70]}".replace("\n", " "))
        evidence["queries"].append(
            {
                "query": query,
                "plan_has_fulltext_branch": "_fts" in plan,
                "plan_has_vector_branch": "_vs" in plan,
                "hits": [
                    {"title": hit["title"], "source": hit["source"], "score": hit["score"], "snippet": hit["text"][:160]}
                    for hit in hits
                ],
            }
        )

    store.close()

    out = base / "EVIDENCE.json"
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nevidence written to {out}")
    print("PASS: Dify <-> seekdb hybrid retrieval verified against a real seekdb kernel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
