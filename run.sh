#!/usr/bin/env bash
# 仓库根目录通用入口 —— 交付物在 qoder/ 目录，本脚本只是转发。
#
#   bash run.sh            # 主功能自检：打印 SELFCHECK PASS，退出码 0（数秒结束）
#   bash run.sh --serve    # 常驻 HTTP 服务 -> http://127.0.0.1:8501
#
# 零第三方依赖、不依赖当前工作目录，也不依赖 bash 之外的东西。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PY=""
for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
    echo "[run.sh] 找不到 python（需要 Python 3.9+）" >&2
    exit 2
fi

exec "$PY" "$HERE/run.py" "$@"
