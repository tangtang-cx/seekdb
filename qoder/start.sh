#!/usr/bin/env bash
# 一键启动（评审用）。优先零依赖入口，任何环境都能起来。
set -u
cd "$(dirname "$0")" || exit 1
PORT="${PORT:-8501}"
if command -v python3 >/dev/null 2>&1; then PY=python3; elif command -v python >/dev/null 2>&1; then PY=python; else
  echo "找不到 python3/python，请先安装 Python 3.9+" >&2; exit 1
fi
echo "使用 $PY 启动：http://127.0.0.1:${PORT}"
exec "$PY" run.py --port "$PORT"
