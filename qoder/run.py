#!/usr/bin/env python3
"""Zero-dependency entry point for the Qoder project.

Two modes, one code path — the rule engine (`reviewer.analyze()`) is the same in
both, and the same one that the Streamlit UI and the published Qoder Sites page run:

    python run.py                 # 模式 A：主流程自检，打印 SELFCHECK PASS，退出码 0（数秒内结束）
    python run.py --serve         # 模式 B：常驻 HTTP 服务 -> http://127.0.0.1:8501
    python run.py --port 9000     # 模式 B（换端口）
    python run.py --streamlit     # 用完整 Streamlit 界面

Works with **no third-party packages at all** (only the Python standard library),
so it can never fail because of a missing wheel or a proxy problem.

Endpoints (mode B)
------------------
GET  /               the interactive reviewer (site/index.html, pure front end)
GET  /health         {"ok": true, "rules_loaded": 15, ...}   (also /_stcore/health)
GET  /api/rules      the 15 deterministic rules
POST /api/review     {"sql": "..."} -> findings, same engine the UI uses
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SITE = HERE / "site"


def _load_engine():
    """Import the rule engine lazily so /health works even if it breaks."""
    from reviewer import analyze, summarize  # noqa: WPS433

    return analyze, summarize


class Handler(SimpleHTTPRequestHandler):
    server_version = "QoderReview/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    # -- helpers ---------------------------------------------------------
    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # keep the console readable
        sys.stderr.write("  %s\n" % (fmt % args))

    # -- routes ----------------------------------------------------------
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/health", "/_stcore/health", "/healthz"):
            try:
                analyze, _ = _load_engine()
                from reviewer import RULES  # noqa: WPS433

                probe_findings = len(analyze("SELECT * FROM t;"))
                self._json({
                    "ok": True,
                    "app": "qoder-review-assistant",
                    "rules_loaded": len(RULES),
                    "probe_findings_on_sample_sql": probe_findings,
                })
            except Exception as error:  # noqa: BLE001
                self._json({"ok": False, "error": f"{type(error).__name__}: {error}"}, 500)
            return
        if path == "/api/rules":
            try:
                analyze, _ = _load_engine()
                from reviewer import RULES  # noqa: WPS433

                self._json({"ok": True, "count": len(RULES), "rules": [
                    {"id": r.id, "level": r.level, "title": r.title} for r in RULES
                ]})
            except Exception as error:  # noqa: BLE001
                self._json({"ok": False, "error": str(error)}, 500)
            return
        if path == "/api/example":
            self._json({"ok": True, "sql": EXAMPLE_SQL})
            return
        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        if self.path.split("?")[0] != "/api/review":
            self._json({"ok": False, "error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            self._json({"ok": False, "error": "invalid json"}, 400)
            return
        sql = (payload.get("sql") or "").strip()
        if not sql:
            self._json({"ok": False, "error": "sql is required"}, 400)
            return
        try:
            analyze, summarize = _load_engine()
            findings = [f.to_dict() for f in analyze(sql)]
            self._json({"ok": True, "sql": sql, "summary": summarize(analyze(sql)), "findings": findings})
        except Exception as error:  # noqa: BLE001
            self._json({"ok": False, "error": f"{type(error).__name__}: {error}"}, 500)


EXAMPLE_SQL = """SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01'
AND c.city LIKE '%杭州%'
LIMIT 20, 200000;"""


def _selfcheck() -> int:
    """Mode A: run the main flow end-to-end and exit (CI / automated review friendly).

    Every declared case is asserted against the rule engine, so a green run means
    "the main function really works", not "the process started".
    """
    analyze, summarize = _load_engine()
    from reviewer import RULES  # noqa: WPS433

    sample_a = (
        "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id\n"
        "WHERE DATE(o.created_at) = '2026-01-01'\n"
        "  AND o.status IN ('NEW', 'PAID', 'SHIPPED', 'DONE')\n"
        "  AND c.city LIKE '%杭州%'\n"
        "ORDER BY o.created_at DESC\n"
        "LIMIT 20, 200000;"
    )
    sample_a_fixed = sample_a.replace("DATE(o.created_at) = '2026-01-01'", "o.created_at >= '2026-01-01'")
    sample_b = "UPDATE orders SET status = 'ARCHIVED';"

    cases = []

    def run_case(name, sql, want, want_ids):
        findings = analyze(sql)
        got = summarize(findings)
        ids = [f.id for f in findings]
        ok = (
            all(got.get(key, 0) == val for key, val in want.items())
            and all(i in ids for i in want_ids)
        )
        cases.append((name, ok, got, ids))
        return ids

    ids_a = run_case("A 慢查询+深分页", sample_a, {"error": 0, "warn": 4, "info": 1},
                     ["OB-004", "OB-005", "OB-006", "OB-007", "OB-013"])
    ids_a2 = run_case("A' 去掉函数包裹", sample_a_fixed, {"error": 0, "warn": 3, "info": 1},
                      ["OB-004", "OB-007"])
    cases[-1] = ("A' 去掉函数包裹后 OB-006 消失", "OB-006" not in ids_a2 and "OB-006" in ids_a,
                 cases[-1][2], ids_a2)
    run_case("B 全表 UPDATE", sample_b, {"error": 1, "warn": 0, "info": 0}, ["OB-001"])
    run_case("C 15 条规则全部加载", "SELECT id FROM t WHERE id = 1;", {}, [])
    cases[-1] = ("C 规则总数", len(RULES) == 15, {"rules": len(RULES)}, [r.id for r in RULES])

    print("[selfcheck] qoder-review-assistant / 零依赖主流程自检", flush=True)
    print(f"[selfcheck] 规则引擎: reviewer.analyze() 已加载 {len(RULES)} 条规则", flush=True)
    passed = 0
    for name, ok, got, ids in cases:
        detail = ", ".join(f"{k}={v}" for k, v in got.items() if k != "rules")
        hit = ", ".join(ids) if ids else "-"
        print(f"[selfcheck] {'PASS' if ok else 'FAIL'}  {name}: {detail or hit}", flush=True)
        if ids and len(ids) <= 6:
            print(f"[selfcheck]        命中: {hit}", flush=True)
        passed += 1 if ok else 0

    if passed == len(cases):
        print(f"SELFCHECK PASS ({passed}/{len(cases)} 用例, {len(RULES)} 条规则)", flush=True)
        return 0
    print(f"SELFCHECK FAIL ({passed}/{len(cases)} 用例通过)", flush=True)
    return 1


def run_streamlit(port: int) -> int:
    import subprocess

    return subprocess.call(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.address=0.0.0.0", "--server.port", str(port),
         "--server.headless=true", "--browser.gatherUsageStats=false"],
        cwd=str(HERE),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Qoder review assistant")
    parser.add_argument("--serve", action="store_true", help="启动常驻 HTTP 服务（模式 B）")
    parser.add_argument("--selfcheck", action="store_true", help="跑完主流程自检后退出（模式 A，默认）")
    parser.add_argument("--port", type=int, default=None, help="服务端口（默认 8501，指定即进入模式 B）")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--streamlit", action="store_true", help="serve the Streamlit UI instead")
    args = parser.parse_args()

    if args.streamlit:
        return run_streamlit(args.port or 8501)

    serve = args.serve or args.port is not None or os.environ.get("SERVE") == "1"
    if not serve:
        return _selfcheck()

    port = args.port or int(os.environ.get("PORT", "8501"))
    server = ThreadingHTTPServer((args.host, port), Handler)
    print(f"Qoder 数据库代码审查助手 -> http://127.0.0.1:{port}", flush=True)
    print("  GET  /            交互式审查界面（零依赖）", flush=True)
    print("  GET  /health      健康检查", flush=True)
    print("  POST /api/review  {\"sql\": \"...\"}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
