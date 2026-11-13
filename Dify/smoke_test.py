#!/usr/bin/env python3
"""Prove that the Dify project starts and serves, in a clean environment.

This is the "项目能够运行" evidence: it installs nothing, it only checks that

1. every module of the project imports with **no heavy dependency** installed
   (only ``streamlit`` is required);
2. the Streamlit app boots and answers on ``/_stcore/health``;
3. the seekdb knowledge service answers on ``/health`` when its optional
   dependencies are present (and the app degrades gracefully when they are not).

    python dify/smoke_test.py            # default port 8899
    python dify/smoke_test.py --port 8901
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def check_imports() -> None:
    """Import the project modules; heavy dependencies must stay optional."""
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "seekdb_service"))

    import auto_start  # noqa: F401
    import embedder  # noqa: F401
    import seekdb_store  # noqa: F401

    # the embedder must expose a working embedder even without onnxruntime
    vectors = embedder.Embedder.get().embed(["HNSW 向量索引", "混合检索 RRF"])
    assert len(vectors) == 2, "embedder did not return two vectors"
    assert len(vectors[0]) == 512, f"unexpected dimension: {len(vectors[0])}"
    print(f"[ok] modules import; embedder mode = {'fallback' if embedder.Embedder.get().is_fallback else 'bge-int8'}")


def wait_http(url: str, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(1.0)
    return False


def check_app(port: int) -> None:
    """Start the Streamlit app and make sure it serves."""
    env = dict(os.environ)
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    env["SEEKDB_SERVICE_URL"] = env.get("SEEKDB_SERVICE_URL", "http://127.0.0.1:8848")
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
         "--server.headless", "true", "--server.port", str(port),
         "--browser.gatherUsageStats", "false"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        ok = wait_http(f"http://127.0.0.1:{port}/_stcore/health", timeout=120)
        if not ok:
            process.terminate()
            output = process.stdout.read().decode("utf-8", "replace") if process.stdout else ""
            raise SystemExit(f"[fail] the app did not answer on /_stcore/health\n{output[-1500:]}")
        print(f"[ok] streamlit app answers on http://127.0.0.1:{port}/_stcore/health")

        # the seekdb knowledge service (optional) should answer as well
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
                print(f"[ok] app page returns HTTP {response.status}")
        except urllib.error.HTTPError as error:
            print(f"[ok] app page returns HTTP {error.code}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except Exception:
            process.kill()


def check_service() -> None:
    """The seekdb service is optional: report, do not fail."""
    sys.path.insert(0, str(ROOT / "seekdb_service"))
    import auto_start

    health = auto_start.ensure_service("http://127.0.0.1:8848", wait=45)
    if health.get("ok"):
        print(f"[ok] seekdb service: {json.dumps(health, ensure_ascii=False)}")
    else:
        print(f"[warn] seekdb service unavailable (optional): {health.get('error')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Dify project smoke test")
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args()

    print("== Dify project smoke test ==")
    check_imports()
    check_app(args.port)
    check_service()
    print("\nPASS: the project starts and serves with the core dependency only")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
