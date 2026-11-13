#!/usr/bin/env bash
# 入口脚本（评审用）。默认跑完主功能自检就退出（退出码 0），
# 与 `python run.py` 行为完全一致；需要常驻服务时加 --serve。
#
#   bash start.sh            # -> SELFCHECK PASS (4/4 用例, 15 条规则)，退出码 0
#   bash start.sh --serve    # -> 常驻 HTTP 服务：http://127.0.0.1:8501
set -u
cd "$(dirname "$0")" || exit 1
PORT="${PORT:-8501}"
if command -v python3 >/dev/null 2>&1; then PY=python3; elif command -v python >/dev/null 2>&1; then PY=python; else
  echo "找不到 python3/python，请先安装 Python 3.9+" >&2; exit 1
fi
if [ "${1:-}" = "--serve" ] || [ "${SERVE:-}" = "1" ]; then
  echo "使用 $PY 启动服务：http://127.0.0.1:${PORT}"
  exec "$PY" run.py --port "$PORT"
fi
echo "使用 $PY 运行主功能自检（加 --serve 可启动常驻服务）"
exec "$PY" run.py
