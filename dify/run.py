#!/usr/bin/env python3
"""Zero-dependency web entry for the Dify project.

`python run.py` serves the same workflow that `app.yml` describes — the DSL's
code node is executed directly, so what you see here is exactly what Dify
returns for the same input.  No Dify, no model, no third-party package.

    python run.py                  # http://127.0.0.1:8501
    python run.py --port 9000

Endpoints
---------
GET  /               a one-page form (paste SQL -> 六段诊断书)
GET  /health         {"ok": true, ...}   (also /_stcore/health)
GET  /api/dsl        which DSL file is being served
POST /api/review     {"sql": "..."} -> {"answer": ..., "summary": ...}

`seekdb_demo.py` is the separate seekdb retrieval demo (needs seekdb running).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DSL_FILE = HERE / "app.yml"
if not DSL_FILE.exists():
    DSL_FILE = HERE / "app.dsl.json"

PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SQL 老中医 · 数据库问诊室</title>
<style>
 :root{--ink:#1f2328;--sub:#656d76;--line:#d0d7de;--bg:#f6f8fa;--brand:#7c3aed}
 *{box-sizing:border-box}
 body{margin:0;font:15px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:var(--ink);background:#fff}
 header{padding:26px 32px 18px;border-bottom:1px solid var(--line);background:var(--bg)}
 h1{margin:0 0 6px;font-size:20px}
 .sub{color:var(--sub);font-size:13px}
 main{max-width:980px;margin:0 auto;padding:24px 20px 60px}
 textarea{width:100%;height:180px;padding:12px;border:1px solid var(--line);border-radius:8px;
   font:13px/1.6 ui-monospace,Consolas,monospace;resize:vertical}
 button{margin-top:12px;padding:9px 22px;border:0;border-radius:8px;background:var(--brand);
   color:#fff;font-size:14px;cursor:pointer}
 button:disabled{opacity:.6;cursor:default}
 #out{margin-top:22px;border:1px solid var(--line);border-radius:10px;padding:18px 20px;
   background:#fff;white-space:pre-wrap;font-size:14px;display:none}
 #meta{margin-top:8px;color:var(--sub);font-size:12px}
</style></head><body>
<header>
  <h1>🩺 SQL 老中医 · 数据库问诊室</h1>
  <div class="sub">贴一段 SQL / DDL，工作流里的「规则体检」节点用 15 条 OceanBase / MySQL 反模式规则判定，输出六段诊断书。</div>
</header>
<main>
  <textarea id="sql">SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01'
AND c.city LIKE '%杭州%'
ORDER BY o.created_at DESC
LIMIT 20, 200000;</textarea>
  <button id="go">开始问诊</button>
  <div id="meta"></div>
  <div id="out"></div>
</main>
<script>
const btn=document.getElementById('go'), out=document.getElementById('out'), meta=document.getElementById('meta');
btn.onclick=async()=>{
  btn.disabled=true; out.style.display='none'; meta.textContent='把脉中…';
  try{
    const r=await fetch('/api/review',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({sql:document.getElementById('sql').value})});
    const d=await r.json();
    if(!d.ok) throw new Error(d.error||'failed');
    out.textContent=d.answer; out.style.display='block';
    meta.textContent='计数：'+(d.summary||'-');
  }catch(e){ meta.textContent='出错了：'+e.message; }
  finally{ btn.disabled=false; }
};
</script></body></html>
"""


def _dsl() -> dict:
    from replay import load_dsl  # noqa: WPS433

    return load_dsl(DSL_FILE)


class Handler(BaseHTTPRequestHandler):
    server_version = "DifyOldTCM/1.0"

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/health", "/_stcore/health", "/healthz"):
            try:
                from replay import execute  # noqa: WPS433

                out = execute(_dsl(), "SELECT * FROM t;")
                self._json({"ok": True, "app": "dify-sql-old-tcm", "has_answer": bool(out.get("answer"))})
            except Exception as error:  # noqa: BLE001
                self._json({"ok": False, "error": f"{type(error).__name__}: {error}"}, 500)
            return
        if path == "/api/dsl":
            self._json({"ok": True, "file": DSL_FILE.name, "path": str(DSL_FILE)})
            return
        self._html(PAGE)

    def do_POST(self):  # noqa: N802
        if self.path.split("?")[0] != "/api/review":
            self._json({"ok": False, "error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads((self.rfile.read(length) if length else b"{}").decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            self._json({"ok": False, "error": "invalid json"}, 400)
            return
        sql = (payload.get("sql") or "").strip()
        if not sql:
            self._json({"ok": False, "error": "sql is required"}, 400)
            return
        try:
            from replay import execute  # noqa: WPS433

            out = execute(_dsl(), sql)
            self._json({"ok": True, "sql": sql, "answer": out.get("answer", ""),
                        "summary": out.get("summary", "")})
        except Exception as error:  # noqa: BLE001
            self._json({"ok": False, "error": f"{type(error).__name__}: {error}"}, 500)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dify SQL 老中医 · 零依赖服务")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8501")))
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"SQL 老中医 -> http://127.0.0.1:{args.port}   (DSL: {DSL_FILE.name})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
