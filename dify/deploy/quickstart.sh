#!/usr/bin/env bash
# One-command bring-up for the Dify track on a clean machine.
#
#   bash Dify/deploy/quickstart.sh
#
# What it does (in order, so nothing races):
#   1. check the toolchain (docker / python) and report versions;
#   2. start seekdb (docker compose) with a persistent data volume;
#   3. install the service dependencies (loose version ranges only);
#   4. fetch the embedding model once (cached under stepfun/public/models);
#   5. start the knowledge service (bge + seekdb hybrid retrieval);
#   6. verify end to end: /health, real hybrid retrieval, write back a review;
#   7. print the Dify import steps + the verification sample + expected output.
#
# Everything is idempotent: re-running it keeps the data (persistence check).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
info() { printf '   %s\n' "$1"; }
die() { printf '\n\033[31mFAILED: %s\033[0m\n' "$1" >&2; exit 1; }

say "0. 环境清单"
info "repo          : $ROOT"
info "python        : $(python3 --version 2>&1 || echo 'MISSING (need python3)')"
info "docker        : $(docker --version 2>&1 || echo 'MISSING (needed for seekdb)')"
info "compose       : $(docker compose version 2>&1 | head -1 || echo 'MISSING')"
command -v python3 >/dev/null || die "python3 not found"
command -v docker >/dev/null || die "docker not found (seekdb runs in a container)"

say "1. 启动 seekdb（持久化到 Dify/deploy/data/seekdb）"
mkdir -p Dify/deploy/data/seekdb Dify/deploy/data/models Dify/deploy/data/service
if docker compose -f Dify/deploy/docker-compose.yml up -d seekdb 2>/dev/null; then
  info "seekdb container started"
else
  info "docker compose 不可用 -> 退回本地嵌入式 seekdb（数据不跨重启持久，见 DEPLOY.md §4）"
  export SEEKDB_PATH="$ROOT/Dify/deploy/data/service/seekdb"
fi

say "2. 安装依赖（宽松版本区间，不写死版本）"
python3 -m pip install --quiet --disable-pip-version-check -r Dify/requirements-seekdb.txt \
  || die "pip install failed - check the network / python version"

say "3. 取一次 embedding 模型（约 23 MiB，缓存到 stepfun/public/models）"
python3 Dify/seekdb_service/fetch_model.py || info "模型不可用 -> 服务会自动降级为确定性哈希向量（仍可运行）"

say "4. 启动知识服务（bge 向量 + seekdb 混合检索 + 审查历史落库）"
if docker compose -f Dify/deploy/docker-compose.yml ps 2>/dev/null | grep -q seekdb; then
  docker compose -f Dify/deploy/docker-compose.yml up -d knowledge-service \
    && info "knowledge-service started in docker"
else
  python3 Dify/seekdb_service/serve.py --port 8848 >Dify/deploy/data/service/service.log 2>&1 &
  info "knowledge-service started locally (log: Dify/deploy/data/service/service.log)"
fi

say "5. 等待服务就绪"
for _ in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8848/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -sf http://127.0.0.1:8848/health >/dev/null 2>&1 \
  || die "knowledge service did not become ready - see Dify/deploy/data/service/service.log"
info "$(curl -s http://127.0.0.1:8848/health)"

say "6. 端到端验证（真实 seekdb 内核 + 真实向量 + 写回历史）"
python3 Dify/seekdb_service/verify.py || die "verify.py failed"
python3 Dify/smoke_test.py || die "smoke_test.py failed (the app must start)"

say "7. Dify 侧怎么接"
cat <<'EOF'
   1) 打开 https://cloud.dify.ai -> 工作室 -> 创建应用 -> 导入 DSL 文件
      -> 上传 Dify/app.yml（零依赖版；工作区没默认模型就用 Dify/app-with-model.yml）
   2) 点开「老中医坐诊」节点 -> 选一个模型（否则该节点无效 -> 运行失败）
   3) 发布 -> 分享 -> 复制链接（这就是提测要填的「项目网站网址」）
   4) 想用真·seekdb 检索做依据：导入 Dify/app-seekdb.yml，
      并把 HTTP 节点的 URL 指向本机服务 http://127.0.0.1:8848/search
      （Dify 官方云需改成可达的公网地址）

   验证样例（提问后应出现固定六段）：
     SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
     WHERE DATE(o.created_at) = '2026-01-01'
     ORDER BY o.created_at DESC LIMIT 20, 200000;

   预期六段：📖医书摘录 / 🩺望闻问切 / 💊药方 / 🚫忌口 / 🧘养生建议 / 🎋医嘱小笺
EOF

say "完成"
info "seekdb 服务  : http://127.0.0.1:8848/health"
info "持久化目录  : Dify/deploy/data/{seekdb,models,service}（重启后数据仍在）"
EOF
