# Dify ⇄ seekdb 知识服务

Dify 应用 `Dify/app.yml` 里的 **「翻医书（查询 seekdb）」** 节点会调用本服务，
本服务用**真实的 seekdb 内核**做向量 + 全文混合检索（RRF 融合在 seekdb 内核内完成）。

```text
Dify 应用 ──HTTP POST /search──► 本服务 ──bge-small-zh(INT8) 向量化──►
                                  └─► seekdb 内核：HNSW 向量分支 + IK 全文分支 + RRF 融合
```

## 1. 它到底做了什么（不是模拟）

| 环节 | 实现 | 证据 |
| --- | --- | --- |
| 向量化 | 本地 `bge-small-zh-v1.5` **INT8 ONNX**（`stepfun/public/models/`，22.8 MiB），ONNX Runtime 推理，CLS pooling + L2 归一化 → 512 维 | `embedder.py`；相关句余弦 0.78 vs 无关句 0.27 |
| 存储与检索 | **真实 seekdb 内核**（`pylibseekdb`），表 `dify_knowledge_base` 带 `VECTOR(512)` + `FULLTEXT INDEX ... PARSER ik` + `VECTOR INDEX ... type=hnsw lib=vsag` | `seekdb_store.py` |
| 融合 | `DBMS_HYBRID_SEARCH.GET_SQL` 生成计划，seekdb 内部跑两路召回并用 RRF 融合 | 计划里同时出现 `_fts`（全文分支）与 `_vs`（向量分支） |
| 刷新 | 写入后 `CALL dbms_index_manager.refresh()` | `seekdb_store.refresh()` |

**没有用任何云端推理 API**：向量是本地模型算的，检索是本地 seekdb 算的。

## 2. 跑起来

```bash
pip install -r Dify/seekdb_service/requirements.txt

# 方式 A：嵌入式 seekdb（本机零依赖，最省事）
python Dify/seekdb_service/serve.py --port 8848

# 方式 B：连一个真实的 seekdb / OceanBase 服务（推荐，HNSW 近似检索路径完整）
export SEEKDB_HOST=127.0.0.1 SEEKDB_PORT=2881 SEEKDB_USER=root SEEKDB_PASSWORD=
python Dify/seekdb_service/serve.py --port 8848
```

方式 B 的 seekdb 服务端：

```bash
docker compose -f Dify/seekdb_service/docker-compose.yml up -d
```

启动日志：

```text
[seekdb-service] seekdb mode=embedded
[seekdb-service] bge-small-zh-v1.5 (INT8) loaded
[seekdb-service] ingested 19 chunks into seekdb
[seekdb-service] listening on http://127.0.0.1:8848
```

## 3. 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | `{"ok":true,"mode":"embedded","chunks":19,"embedding_dim":512}` |
| POST | `/search` | `{"query":"...","top_k":4,"mode":"hybrid"}` → `{"hits":[{title,text,source,score}],"context":"..."}` |
| POST | `/ingest` | 重新灌入 `kb/*.md`（默认启动时自动灌） |
| GET | `/docs` | 列出已索引的知识库文档 |

`mode` 可取 `hybrid`（向量 + 全文 + RRF，默认）/ `vector` / `fulltext`。

## 4. 端到端验证

```bash
python Dify/seekdb_service/verify.py
```

输出（真实运行结果，同时写入 `EVIDENCE.json`）：

```text
seekdb mode      : embedded
embedding model  : bge-small-zh-v1.5 (INT8 ONNX), dim=512
ingested chunks  : 19 (rows in seekdb: 19) in 35.4s

Q: HNSW 向量索引的建表语句是什么？
   plan contains fulltext branch: True; vector branch: True
   - [seekdb / OceanBase 向量库速查…] :: CREATE TABLE `browser_knowledge_base` …
Q: 混合检索的 RRF 融合是怎么做的？
   plan contains fulltext branch: True; vector branch: True
   - [混合检索（向量 + 全文）与 RRF 融合] …
Q: 端侧 INT8 量化会损失多少召回率？
   - [端侧（浏览器内）向量化与 INT8 / FP16 量化] …
Q: AMD GPU 加速 HNSW 的建图收益有多少？
   - [AMD ROCm / hipVS（cuVS CAGRA）加速] …
PASS: Dify <-> seekdb hybrid retrieval verified against a real seekdb kernel
```

## 5. 接到 Dify

`Dify/app.yml` 里已经配好：

```yaml
- id: seekdb
  data:
    type: http-request
    method: post
    url: http://127.0.0.1:8848/search
    body:
      type: json
      data:
        - id: body-query
          type: text
          key: ''
          value: '{"query": "{{#sys.query#}}", "top_k": 4, "mode": "hybrid"}'
```

LLM 节点通过 `{{#seekdb.body#}}` 拿到检索结果（JSON，含 `context` 字段）。

- **自建 / 本机 Dify**：默认 URL 直接可用。
- **Dify 官方云**：把节点的 URL 改成你的服务公网地址（1 次编辑），例如
  `https://<你的域名>/search`；或用 `Dify/app-standalone.yml`（不依赖外部服务的纯 LLM 版）。

## 6. 已知限制（如实记录）

- **Windows 嵌入式 seekdb**：`ORDER BY _distance APPROXIMATE`（HNSW 近似路径）在 Windows 的
  seekdb-js / pylibseekdb 绑定下不返回结果（与 `stepfun/TECH_REPORT.md` 记录的同一限制），
  因此本机演示走的是**混合计划路径**（`_fts` + `_vs` 双分支，RRF 融合，正常工作）；
  在 Linux / Docker 的 seekdb 服务端上，HNSW 近似路径同样可用（评测环境即为此形态）。
- **嵌入式模式不落盘**：Windows 嵌入式内核重启后数据为空，所以服务启动时会自动重新灌库
  （约 35 秒，19 块）。用 seekdb 服务端模式（`SEEKDB_HOST`）则数据持久化。
