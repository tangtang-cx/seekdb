"""HTTP service that exposes the seekdb knowledge base to Dify.

Endpoints
---------
``GET  /health``            -> {"ok": true, "mode": "embedded", "chunks": 42, ...}
``POST /search``            -> {"query": "...", "top_k": 5}
                                returns {"hits": [{title, text, source, distance}], ...}
``POST /ingest``            -> {"docs": [{title, text, source}]} (rebuild the KB)
``GET  /docs``              -> list of the knowledge-base titles currently indexed

Run:

    pip install pylibseekdb onnxruntime tokenizers numpy
    python Dify/seekdb_service/serve.py --port 8848

The Dify app calls it through an HTTP Request node
(``Dify/app.yml`` -> node ``seekdb`` -> ``POST {base_url}/search``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from embedder import Embedder  # noqa: E402
from seekdb_store import SeekdbStore, chunk_text  # noqa: E402

KB_DIR = Path(__file__).resolve().parent.parent / "kb"
STATE: dict[str, object] = {"store": None, "embedder": None, "lock": threading.Lock()}


def load_kb_documents(kb_dir: Path = KB_DIR) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for path in sorted(kb_dir.glob("*.md")):
        title = path.stem
        text = path.read_text(encoding="utf-8")
        heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if heading:
            title = heading.group(1).strip()
        docs.append({"title": title, "text": text, "source": path.name})
    return docs


def ingest(store: SeekdbStore, embedder: Embedder, docs: list[dict[str, str]]) -> int:
    rows: list[dict[str, object]] = []
    for doc in docs:
        for index, chunk in enumerate(chunk_text(doc["text"])):
            digest = hashlib.sha256(f"{doc['source']}::{index}::{chunk}".encode("utf-8")).hexdigest()[:20]
            rows.append(
                {
                    "id": digest,
                    "text": chunk,
                    "embedding": embedder.embed_one(chunk),
                    "metadata": {"title": doc["title"], "source": doc["source"], "chunk": index},
                }
            )
    return store.upsert(rows)


class Handler(BaseHTTPRequestHandler):
    server_version = "dify-seekdb/1.0"

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # keep the console readable
        sys.stderr.write("[seekdb-service] " + (fmt % args) + "\n")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._json({})

    def do_GET(self) -> None:  # noqa: N802
        store = STATE["store"]
        if self.path.rstrip("/") == "/health":
            self._json(store.health())
            return
        if self.path.rstrip("/") == "/docs":
            docs = load_kb_documents()
            self._json({"docs": [{"title": d["title"], "source": d["source"]} for d in docs]})
            return
        if self.path.rstrip("/") == "/reviews":
            with STATE["lock"]:
                self._json({"reviews": store.list_reviews(20)})
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        store: SeekdbStore = STATE["store"]
        embedder: Embedder = STATE["embedder"]
        payload = self._read_json()

        if self.path.rstrip("/") == "/search":
            query = str(payload.get("query", "")).strip()
            top_k = int(payload.get("top_k", 5))
            mode = str(payload.get("mode", "hybrid"))
            if not query:
                self._json({"query": "", "hits": [], "took_ms": 0})
                return
            started = time.time()
            embedding = embedder.embed_one(query)
            with STATE["lock"]:
                hits = store.search(query, embedding, top_k, mode)
            took = int((time.time() - started) * 1000)
            self._json(
                {
                    "query": query,
                    "engine": "seekdb",
                    "mode": mode,
                    "took_ms": took,
                    "hits": hits,
                    "context": "\n\n".join(f"[{i + 1}] {h['title']}\n{h['text']}" for i, h in enumerate(hits)),
                }
            )
            return

        if self.path.rstrip("/") == "/ingest":
            docs = payload.get("docs") or load_kb_documents()
            with STATE["lock"]:
                count = ingest(store, embedder, docs)
            self._json({"ok": True, "ingested": count, "chunks": store.count()})
            return

        if self.path.rstrip("/") == "/reviews":
            # write one review round into seekdb (Qoder track: storage + query)
            findings = payload.get("findings") or []
            with STATE["lock"]:
                review_id = store.write_review(
                    engine=str(payload.get("engine", "rules")),
                    sql_text=str(payload.get("sql", "")),
                    findings=findings,
                    summary=str(payload.get("summary", "")),
                    kb_hits=int(payload.get("kb_hits", 0)),
                )
            self._json({"ok": True, "id": review_id, "reviews": store.review_count()})
            return

        self._json({"error": "not found"}, 404)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dify <-> seekdb knowledge service")
    parser.add_argument("--host", default=os.environ.get("SEEKDB_SERVICE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("SEEKDB_SERVICE_PORT", "8848")))
    parser.add_argument("--no-ingest", action="store_true", help="skip loading kb/*.md at startup")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    print("[seekdb-service] starting ...", flush=True)

    store = SeekdbStore()
    store.open()
    print(f"[seekdb-service] seekdb mode={store.mode}", flush=True)

    embedder = Embedder.get()
    print("[seekdb-service] bge-small-zh-v1.5 (INT8) loaded", flush=True)

    if not args.no_ingest:
        count = ingest(store, embedder, load_kb_documents())
        print(f"[seekdb-service] ingested {count} chunks into seekdb", flush=True)

    STATE["store"] = store
    STATE["embedder"] = embedder

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[seekdb-service] listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[seekdb-service] shutting down", flush=True)
    finally:
        server.server_close()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

