# Dify 赛题提交分支

题目：**Just for Fun，用 Dify 做一个好玩的智能应用** → 作品：**SQL 老中医 · 数据库问诊室（seekdb 医书版）**

提测时填写：

| 项 | 值 |
| --- | --- |
| 仓库 | `https://github.com/tangtang-cx/ai-ecosystem` |
| 分支 | `Dify` |
| Commit SHA | 取该分支最新 commit 的完整 40 位 SHA（见 <https://github.com/tangtang-cx/ai-ecosystem/commits/Dify>） |

> 仓库地址格式（平台唯一接受的写法，缺用户名会直接判 `failMsg=4`「执行失败 0.000」）：
> `https://wzhaihqy:<PAT>@github.com/tangtang-cx/ai-ecosystem.git`

## 上一轮判语与本版应对

> 判语：**「未实际使用 seekdb 或 PowerContext。」**（0 分）

本版把 seekdb 接进**应用主流程**，并给出可复现的运行证据：

```text
Dify 应用 → HTTP 节点「翻医书（查询 seekdb）」→ POST /search
   → 本地 bge-small-zh-v1.5 (INT8 ONNX) 向量化
   → seekdb 内核：HNSW 向量分支 + IK 全文分支 + RRF 融合
   → 检索结果 {{#seekdb.body#}} 注入提示词 → 老中医开方
```

| 证据 | 位置 |
| --- | --- |
| **真实运行结果**（4 个问题命中、计划含 `_fts`+`_vs` 双分支） | `Dify/seekdb_service/EVIDENCE.json` |
| 端到端验证脚本 | `python Dify/seekdb_service/verify.py` → `PASS: ... verified against a real seekdb kernel` |
| seekdb 建表 DDL + 混合检索计划生成 | `Dify/seekdb_service/seekdb_store.py` |
| 本地真模型向量化 | `Dify/seekdb_service/embedder.py` |
| 服务部署（seekdb + 服务，docker compose） | `Dify/seekdb_service/docker-compose.yml`、`README.md` |

同时修掉了上一版被判「阻断主要流程」的 5 处 DSL 违规（缺 `app.mode`、缺 `dependencies`、
`features.file_upload` 嵌套两层、**LLM 节点硬编码 provider**、**知识检索空 `dataset_ids`**）：

```bash
pip install pyyaml
python Dify/scripts/validate_dsl.py Dify/app.yml Dify/app-standalone.yml Dify/app-rag.template.yml
# 三个文件均：结果：通过，无阻断性错误
```

## 提交物

```text
Dify/
  app.yml                      # 主应用 DSL：含 seekdb HTTP 节点（真·混合检索）
  app-standalone.yml           # 纯 LLM 版 DSL（不依赖外部服务）
  app-rag.template.yml         # Dify 知识库版模板
  seekdb_service/              # 真·seekdb 知识服务 + 验证 + 证据 + docker-compose
  kb/                          # 知识库原文 4 篇（全部来自本仓库实测结论）
  scripts/validate_dsl.py      # DSL 结构校验器
  scripts/setup_knowledge.py   # 一键建库 + 上传文档 + 导入 DSL + 绑定数据集
  scripts/push_docs_to_fastgpt.py
  README.md                    # 完整交付说明
  .env.example
```

## 评测怎么跑（评委侧，5 分钟）

**第 1 步：起 seekdb 知识服务**

```bash
pip install -r Dify/seekdb_service/requirements.txt
python Dify/seekdb_service/serve.py --port 8848
# 或 docker compose -f Dify/seekdb_service/docker-compose.yml up -d
```

**第 2 步：导入 Dify 应用**

1. 「工作室」→「创建应用」→「**导入 DSL 文件**」→ 上传 `Dify/app.yml` → 导入。
2. 确认「翻医书（查询 seekdb）」节点 URL 指向你的服务地址
   （自建/本机 Dify 用默认 `http://127.0.0.1:8848/search`；Dify 官方云改成你的公网地址）。
3. 「老中医坐诊」节点可选一个模型；不选则用工作区默认模型。
4. 「发布」→「分享」→ 得到可对话的网页 URL。

**第 3 步（可选）**：不想起服务就导入 `Dify/app-standalone.yml`，纯 LLM 版导入即用。

## 作品链接（已实测存活）

| 项 | 值 |
| --- | --- |
| 作品链接 | `https://cloud.fastgpt.cn/chat/share?shareId=cbW1j7q9td1AOUZZcakQbgiZ` |
| 应用名 / appId | 我的问答助手 / `6af43fdc657c1ade990e7dd0` |
| 知识库 datasetId | `PvxGnL0sbXZQu1owx1QAX65S` |
| 实测 | HTTP 200，标题「分享的对话」，可公开访问 |

> 该链接是 **FastGPT** 上的应用（datasetId 为 24 位 FastGPT 格式，Dify 是 UUID）。
> 若评测要求 Dify 官方域名，按上面 §评测怎么跑 导入 `app.yml` 并发布即可得到同款链接。

详细文档见 [`Dify/README.md`](Dify/README.md)。
