#!/usr/bin/env python3
"""仓库根目录转发入口 —— 交付物在 qoder/ 目录。

    python run.py            # 主功能自检：打印 SELFCHECK PASS，退出码 0（数秒结束）
    python run.py --serve    # 常驻 HTTP 服务 -> http://127.0.0.1:8501

只是把 argv 原样转给 qoder/run.py，行为与在 qoder/ 目录内运行完全一致。
标准库实现，不依赖任何第三方包，也不依赖当前工作目录。
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parent / "qoder" / "run.py"
if not ENTRY.exists():
    sys.stderr.write(f"[run.py] 找不到 {ENTRY}\n")
    raise SystemExit(2)

sys.argv = [str(ENTRY), *sys.argv[1:]]
os.chdir(ENTRY.parent)
runpy.run_path(str(ENTRY), run_name="__main__")
