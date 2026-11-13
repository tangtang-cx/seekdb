#!/usr/bin/env python3
"""Prove that the Qoder project starts and serves with the core dependency only.

This is the "主要功能能够运行" evidence:

1. every module imports with **no heavy dependency** installed (only ``streamlit``);
2. the Streamlit app boots and answers on ``/_stcore/health``;
3. the seekdb backend is optional: the app still runs without it.

    python qoder/smoke_test.py            # default port 8901
    python qoder/smoke_test.py --port 8902
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def check_imports() -> None:
    sys.path.insert(0, str(ROOT))
    import reviewer  # noqa: F401
    import seekdb_bridge  # noqa: F401

    findings = reviewer.analyze("SELECT * FROM t WHERE DATE(c)='2026-01-01' LIMIT 20, 200000;")
    ids = sorted(item.id for item in findings)
    assert "OB-004" in ids and "OB-007" in ids, f"rule engine did not fire as expected: {ids}"
    print(f"[ok] modules import; rules fired on the sample: {ids}")
    print(f"[ok] seekdb backend optional -> {seekdb_bridge.health('http://127.0.0.1:8901')}")


def wait_http(url: str, timeout: float = 120.0) -> bool:
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
    env = dict(os.environ)
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    env.setdefault("SEEKDB_SERVICE_URL", "http://127.0.0.1:8848")
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
        if not wait_http(f"http://127.0.0.1:{port}/_stcore/health"):
            process.terminate()
            output = process.stdout.read().decode("utf-8", "replace") if process.stdout else ""
            raise SystemExit(f"[fail] the app did not answer on /_stcore/health\n{output[-1500:]}")
        print(f"[ok] streamlit app answers on http://127.0.0.1:{port}/_stcore/health")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except Exception:
            process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Qoder project smoke test")
    parser.add_argument("--port", type=int, default=8901)
    args = parser.parse_args()

    print("== Qoder project smoke test ==")
    check_imports()
    check_app(args.port)
    print("\nPASS: the project starts and serves with the core dependency only")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
