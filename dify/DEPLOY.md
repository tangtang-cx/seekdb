# Dify 赛题 · 评测环境从零复现手册

> **本文档描述的是可选增强，不是评测对象。**
> 主交付是 `app.yml`（workflow：开始 → 规则体检 code 节点 → 出方），
> **不需要 seekdb、不需要模型、不需要外部服务**。下面这套 seekdb 检索增强
> 只在你想看「真·向量检索」时使用，评测时可以完全忽略。

> 目标：让评审在**一台干净的机器/容器**上，按本文从安装依赖 → 初始化数据 → 启动应用 →
> 跑验证样例，**不需要任何作者本地的残留状态**（模型权重、数据库、配置一律由本文给出）。

---

## 0. 提交信息（先核对，最常见的失败原因）

| 项 | 值 |
| --- | --- |
| 代码仓库 | `https://<用户名>:<令牌>@github.com/tangtang-cx/seekdb.git`（**私有**，官方不允许 Public 参赛） |
| 分支 | `2026-competition-ecosystem`（官方基线同名分支；其父提交 = 官方基线 `d647275c`） |
| Commit | `02ae3faf7f9b1b235369bfac9f8c64af8d38a393`（该分支当前 head） |
| 资产目录 | `dify/`（同时含 `qoder/` `gaode/` `stepfun/` `minimax/` `modelscope/`） |
| 项目网站 | cloud.dify.ai 上导入 `dify/app.yml` 后发布的分享链接 |

> 自查（提交前跑一次，30 秒）：
> ```bash
> export GITHUB_TOKEN=<你的 PAT>
> node tools/check_submission.mjs 2026-competition-ecosystem <40位commit> dify
> # 期望：4 个 ok + RESULT: submittable
> ```
> 它会验证：仓库可读 → **分支存在（大小写敏感）** → **commit 确实是该分支的 head 或祖先**
> → 资产目录非空。

---

## 1. 环境清单

| 组件 | 版本 | 必需？ | 说明 |
| --- | --- | --- | --- |
| OS | Linux x86_64 / macOS / Windows | — | 我们的服务在 Linux 上验证过；Windows 也能跑（见 §6 限制） |
| Python | 3.9 ~ 3.13 | ✅ | 仅需 `streamlit` 即可启动应用 |
| Docker | 20.10+ | ⭕（推荐） | 用来跑 seekdb 服务端（持久化 + 完整 HNSW 近似路径） |
| CPU / 内存 | 2 核 / 4 GB | — | 无 GPU 需求；bge 是 INT8 ONNX，CPU 推理 |
| 网络 | 能拉 docker 镜像与 pip 包 | ✅ | 首次需要；之后模型已缓存 |
| 模型服务 | 任意 OpenAI 兼容（通义 / DeepSeek / MiniMax / StepFun / 魔搭） | ⭕ | 不配也能用：只跑规则层 + 展示 seekdb 检索到的医书原文 |
| **Dify 插件** | **我们不依赖任何插件** | — | 因此不存在 `dify-plugin-daemon` 重启丢插件的问题 |

---

## 2. 架构与「seekdb 到底承担什么」

```text
                   ┌──────────────────────────────┐
  评审浏览器  ──▶  │  Dify 应用（cloud.dify.ai 或自建） │
                   │   开始 → 老中医坐诊(LLM) → 出方 │
                   └───────────────┬──────────────┘
                                   │ HTTP（可选增强版 app-seekdb.yml）
                                   ▼
                   ┌──────────────────────────────┐
                   │  知识服务 (8848)              │
                   │   bge-small-zh INT8 向量化    │
                   │   → seekdb 混合检索(向量+全文+RRF) │
                   │   → 审查历史写回 seekdb        │
                   └───────────────┬──────────────┘
                                   ▼
                   ┌──────────────────────────────┐
                   │  seekdb（真数据库内核）        │
                   │   dify_knowledge_base        │
                   │     VECTOR(512) + IK 全文      │
                   │     + HNSW 向量索引(vsag)     │
                   │   qoder_review_log（应用数据）  │
                   └──────────────────────────────┘
```

**技术结合的分工（官方允许的两种形态我们都给了）**：

| 形态 | seekdb 承担 | 交付物 | 核验方式 |
| --- | --- | --- | --- |
| A. **Dify 的部署数据库** | Dify 自身的工作区/应用/会话等元数据 | [`DIFY_SEEKDB_DEPLOY.md`](DIFY_SEEKDB_DEPLOY.md) | 部署配置 + 建库初始化 + 读写验证步骤 |
| B. **配套后端**（知识向量存储 + 应用数据存储） | ① 知识库向量存储：`dify_knowledge_base`（`VECTOR(512)` + IK 全文 + HNSW）<br>② 应用数据存储：审查/问诊历史 `qoder_review_log` | `seekdb_service/`（真内核 + 本地 bge + RRF） | [`EVIDENCE_ROOT.json`](EVIDENCE_ROOT.json)（真实建表/写入/双分支检索/写回记录）+ `verify.py` 可复现 |

> 官方原文：*「只要 seekdb 实际承担所声明的数据存储职责，且应用的主要功能可按说明正常体验，
> 即满足 seekdb 的使用要求，无需在工作流中额外增加直接调用 seekdb 的节点。」*
> 我们的应用**同时**满足两条：工作流里可直连 seekdb（增强版），且 seekdb 真实承担知识与历史存储。

---

## 3. 一键部署（干净机器）

```bash
git clone https://github.com/tangtang-cx/seekdb.git
cd seekdb
bash Dify/deploy/quickstart.sh
```

脚本按顺序做完：环境自检 → 起 seekdb（持久化卷）→ 装依赖 → 取一次模型权重 →
起知识服务 → **端到端验证**（`verify.py` + `smoke_test.py`）→ 打印 Dify 导入步骤与样例。

---

## 4. 持久化（评测机重启场景）

| 数据 | 位置 | 重启后 |
| --- | --- | --- |
| seekdb 数据 | `Dify/deploy/data/seekdb`（Docker 卷）/ `SEEKDB_PATH` | ✅ 保留 |
| bge 模型权重 | `stepfun/public/models/bge-small-zh-v1.5`（缓存目录 `Dify/deploy/data/models`） | ✅ 保留 |
| 知识服务运行态 | `Dify/deploy/data/service` | ✅ 保留 |
| Dify 自身（若自建） | 见 `DIFY_SEEKDB_DEPLOY.md` §3：**必须**给 DB / 向量库 / 文件存储挂持久卷 | ✅ 保留 |
| Dify 插件 | **我们不依赖任何插件** | 无插件状态可丢 |

> ⚠️ Dify 默认把数据库、向量库、文件存储放在**容器临时文件系统**里，重启即清空。
> 自建 Dify 时务必照 `DIFY_SEEKDB_DEPLOY.md` §3 给这三样挂卷，否则重启后知识库会"消失"。

**重启恢复自检**（部署完做一次）：

```bash
docker compose -f Dify/deploy/docker-compose.yml restart seekdb knowledge-service
sleep 30
curl -s http://127.0.0.1:8848/health     # 期望 chunks 仍是 19，不是 0
python3 Dify/seekdb_service/verify.py     # 期望 4 个问题仍然全部命中
```

---

## 5. 依赖与启动顺序（避免「web 早于 DB 启动」）

`Dify/deploy/docker-compose.yml` 已经处理好：

```yaml
knowledge-service:
  depends_on:
    seekdb:
      condition: service_healthy     # 等 seekdb 真正 ready 才起服务
  healthcheck: ...                    # 服务自身也有探针
```

手工部署时也遵守这个顺序：**seekdb →（healthy）→ 知识服务 →（healthy）→ Dify**。

环境变量清单（全部用占位值，不提交真实凭据）：

| 变量 | 用途 | 默认 |
| --- | --- | --- |
| `SEEKDB_HOST` / `SEEKDB_PORT` | seekdb 服务端地址 | `seekdb` / `2881` |
| `SEEKDB_USER` / `SEEKDB_PASSWORD` / `SEEKDB_DATABASE` | 数据库账号 | `root` / 空 / `test` |
| `BGE_MODEL_DIR` | 模型权重目录 | `stepfun/public/models/bge-small-zh-v1.5` |
| `SEEKDB_SERVICE_URL` | Dify/Qoder 应用侧的服务地址 | `http://127.0.0.1:8848` |
| `MODELSCOPE_API_KEY` / `MINIMAX_API_KEY` / `STEPFUN_API_KEY` | 可选，OpenAI 兼容推理 | 空（不填也能用） |

---

## 6. 已知限制（如实说明）

- **Windows 嵌入式 seekdb**：`ORDER BY _distance APPROXIMATE`（HNSW 近似路径）在 Windows 的
  seekdb-js / pylibseekdb 绑定下不返回结果（与 `stepfun/TECH_REPORT.md` 记录的同一限制），
  因此本机演示走**混合计划路径**（`_fts` + `_vs` 双分支、RRF 融合，正常工作）；
  Linux / Docker 的 seekdb 服务端上 HNSW 近似路径同样可用（评测环境即为此形态）。
- **嵌入式模式不跨重启持久**：Windows 嵌入式内核重启后数据为空，所以服务启动时会自动重新灌库
  （约 35 秒、19 块）；用 seekdb **服务端**模式（Docker / `SEEKDB_HOST`）则数据持久化。
- **模型权重不在仓库里**（23 MiB，太大）：`fetch_model.py` 取一次，或服务自动降级为
  确定性字符 n-gram 哈希向量（512 维、L2 归一化）——**seekdb 的存储、HNSW 索引、向量分支与
  RRF 融合依然完整可用**，只是语义质量下降。
- **不填模型 Key** 时应用仍可用：规则层照常工作，并直接展示从 seekdb 检索到的医书原文。

---

## 7. 验证样例与预期表现

**输入**：

```sql
SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01'
  AND o.status IN ('NEW', 'PAID', 'SHIPPED', 'DONE')
  AND c.city LIKE '%杭州%'
ORDER BY o.created_at DESC
LIMIT 20, 200000;
```

**预期（固定六段，顺序不变、缺一不可）**：

```text
## 📖 医书摘录     ← 《OceanBase / seekdb 医书》里与「函数包裹索引列 / 深分页 / SELECT *」相关的条目
## 🩺 望闻问切     ← ≥3 条：SELECT * 全列回表、DATE(col) 索引失效、深分页扫描丢行
## 💊 药方         ← 显式列 + created_at 范围条件 + 游标分页（可直接粘贴运行）
## 🚫 忌口         ← 不要在索引列套函数、不要大 OFFSET
## 🧘 养生建议     ← 给 orders(created_at) 建索引 / 覆盖索引带排序列
## 🎋 医嘱小笺     ← 俏皮话 + 最该先改的那处
```

**seekdb 真的在起作用的记录**：`EVIDENCE_ROOT.json` 里每条检索都带
`plan_has_fulltext_branch=true` 与 `plan_has_vector_branch=true`（即 seekdb 内核同时执行了
全文分支与向量分支），另有 `writes.knowledge_chunks=19`、`writes.review_log_rows`（写回历史）。

**边界场景**（评测常查）：

| 场景 | 表现 |
| --- | --- |
| 重复输入同一段 SQL | 结果一致；审查历史按轮次追加，不产生重复脏数据 |
| seekdb 服务不可用 | 侧边栏明确提示「seekdb 未就绪：…」，**应用不崩**，规则层照常工作 |
| 大模型超时/报错 | 捕获后提示「模型调用失败：…」，seekdb 已写入的检索依据照常展示 |
| 重启服务 | 服务端模式下数据仍在（§4 自检命令） |
| 并发多会话 | 每个会话独立，seekdb 连接由服务端统一管理 |

---

## 8. 提交材料对照

| 材料 | 在哪 |
| --- | --- |
| Dify DSL | `dify/app.yml`（主）、`dify/app-with-model.yml`、`dify/app-seekdb.yml`、`dify/app-rag.template.yml` |
| 运行说明 | 本文件 + `dify/README.md` |
| 验证样例 | 本文件 §7 + `dify/README.md` §4 |
| seekdb 部署配置 | `dify/DIFY_SEEKDB_DEPLOY.md` + `dify/deploy/docker-compose.yml` |
| 实际读写记录 | `dify/EVIDENCE_ROOT.json` + `dify/seekdb_service/EVIDENCE.json` |
| 能跑自证 | `dify/smoke_test.py`（PASS）、`dify/seekdb_service/verify.py`（PASS） |
