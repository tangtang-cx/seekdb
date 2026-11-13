#!/usr/bin/env python3
"""别名入口：``python main.py`` 等价于 ``python run.py``。

自动评测脚本有时按「主程序」的常见约定去找 ``main.py``，这里保证它存在，
且行为与 ``run.py`` 完全一致（默认跑完主功能自检就退出，退出码 0）。
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parent / "run.py"
if not ENTRY.exists():
    sys.stderr.write(f"[main.py] 找不到 {ENTRY}\n")
    raise SystemExit(2)

sys.argv = [str(ENTRY), *sys.argv[1:]]
runpy.run_path(str(ENTRY), run_name="__main__")
