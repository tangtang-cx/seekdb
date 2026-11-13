#!/usr/bin/env python3
"""一句话验收脚本 —— 面向评审/评测机，零第三方依赖。

    python verify.py           # 跑全部检查，逐项打印 PASS/FAIL，退出码 0 表示通过
    python verify.py --quiet   # 只打印最后一行结论

检查项（对应赛题说明 3.1 基础验收）：
  1. 规则引擎可加载：15 条规则全部注册
  2. 验证样例可复现：A / A' / B / C 四组样例的三级计数与命中规则号
  3. 常驻服务可启动：/health 返回 ok
  4. 审查接口可用：POST /api/review 返回同一套 findings

全部为本机离线检查，不需要网络、不需要 seekdb、不需要模型 Key。
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE_SQL = (
    "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id\n"
    "WHERE DATE(o.created_at) = '2026-01-01'\n"
    "  AND o.status IN ('NEW', 'PAID', 'SHIPPED', 'DONE')\n"
    "  AND c.city LIKE '%杭州%'\n"
    "ORDER BY o.created_at DESC\n"
    "LIMIT 20, 200000;"
)
EXPECTED = {"error": 0, "warn": 4, "info": 1, "ids": ["OB-004", "OB-005", "OB-006", "OB-007", "OB-013"]}

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> bool:
    results.append((name, ok, detail))
    if "--quiet" not in sys.argv:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)
    return ok


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def check_engine() -> bool:
    sys.path.insert(0, str(HERE))
    try:
        from reviewer import RULES, analyze, summarize  # noqa: PLC0415
    except Exception as error:  # noqa: BLE001
        return record("规则引擎导入", False, f"{type(error).__name__}: {error}")
    count = len(RULES)
    findings = analyze(SAMPLE_SQL)
    ids = [finding.id for finding in findings]
    summary = summarize(findings)
    ok = (
        count == 15
        and summary["error"] == EXPECTED["error"]
        and summary["warn"] == EXPECTED["warn"]
        and summary["info"] == EXPECTED["info"]
        and ids == EXPECTED["ids"]
    )
    return record(
        "规则引擎与验证样例",
        ok,
        f"规则 {count} 条；样例 SQL -> error={summary['error']} warn={summary['warn']} "
        f"info={summary['info']}，命中 {', '.join(ids)}",
    )


def check_selfcheck() -> bool:
    code = subprocess.run([sys.executable, str(HERE / "run.py")], cwd=str(HERE), capture_output=True, text=True, timeout=120)
    tail = [line for line in code.stdout.splitlines() if line.strip()][-1:] or [""]
    return record("python run.py 自检", code.returncode == 0, f"退出码 {code.returncode}；{tail[0].strip()[:80]}")


def check_service() -> bool:
    port = free_port()
    process = subprocess.Popen(
        [sys.executable, str(HERE / "run.py"), "--serve", "--port", str(port)],
        cwd=str(HERE),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        health = None
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"{base}/health", timeout=1) as response:
                    health = json.load(response)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.25)
        if not health:
            return record("常驻服务 /health", False, "10 秒内未启动")
        record("常驻服务 /health", bool(health.get("ok")), f"rules_loaded={health.get('rules_loaded')}")
        request = urllib.request.Request(
            f"{base}/api/review",
            data=json.dumps({"sql": SAMPLE_SQL}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)
        summary = payload["summary"]
        ids = [item["id"] for item in payload["findings"]]
        ok = summary == {"error": 0, "warn": 4, "info": 1} and ids == EXPECTED["ids"]
        return record("POST /api/review", ok, f"error={summary['error']} warn={summary['warn']} info={summary['info']}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    check_engine()
    check_selfcheck()
    check_service()
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    if passed != total:
        print(f"VERIFY FAIL ({passed}/{total})", flush=True)
        return 1
    print(f"VERIFY PASS ({passed}/{total} 项检查全部通过)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
