"""Start the seekdb service automatically when it is not running yet.

Both the Dify app (``dify/app.py``) and the Qoder reviewer (``qoder/app.py``)
need the seekdb knowledge service. To keep every project runnable with a single
command, this helper starts the service **in-process** (a background thread) when
the configured address is not reachable yet.

    from seekdb_service.auto_start import ensure_service
    ensure_service("http://127.0.0.1:8848")
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent

# last startup error of the in-process service thread (surfaced to the UI)
STATE: dict[str, object] = {"error": None}


def _split_base(base_url: str) -> tuple[str, int]:
    trimmed = base_url.rstrip("/")
    if "://" in trimmed:
        trimmed = trimmed.split("://", 1)[1]
    host, _, port = trimmed.partition(":")
    return host or "127.0.0.1", int(port or 8848)


def _reachable(base_url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/health", timeout=timeout):
            return True
    except Exception:
        return False


def ensure_service(base_url: str = "http://127.0.0.1:8848", *, wait: float = 90.0) -> dict:
    """Return the service health dict, starting the service when needed."""
    if _reachable(base_url):
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/health", timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    host, port = _split_base(base_url)
    sys.path.insert(0, str(SERVICE_DIR))
    try:
        from serve import Handler, ingest, load_kb_documents  # noqa: WPS433
        from http.server import ThreadingHTTPServer
        from embedder import Embedder
        from seekdb_store import SeekdbStore
    except Exception as error:  # pragma: no cover - dependency problem
        return {"ok": False, "error": f"cannot import the seekdb service: {error}"}

    def _run() -> None:
        try:
            store = SeekdbStore()
            store.open()
            embedder = Embedder.get()
            try:
                count = store.count()
            except Exception:
                count = 0
            if count == 0:
                try:
                    ingest(store, embedder, load_kb_documents())
                except Exception:
                    pass
            server = ThreadingHTTPServer((host, port), Handler)
            server.serve_forever()
        except BaseException as error:  # noqa: BLE001 - surface the reason to the UI
            STATE["error"] = f"{type(error).__name__}: {error}"

    thread = threading.Thread(target=_run, daemon=True, name="seekdb-service")
    thread.start()

    deadline = time.time() + wait
    while time.time() < deadline:
        if _reachable(base_url, timeout=1.0):
            with urllib.request.urlopen(f"{base_url.rstrip('/')}/health", timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        if STATE.get("error"):
            return {"ok": False, "error": f"seekdb service failed to start: {STATE['error']}"}
        time.sleep(1.0)
    return {"ok": False, "error": "the seekdb service did not become ready in time"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="start the seekdb service in the foreground")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8848)
    args = parser.parse_args()
    sys.path.insert(0, str(SERVICE_DIR))
    from serve import main as serve_main

    raise SystemExit(serve_main(["--host", args.host, "--port", str(args.port)]))
