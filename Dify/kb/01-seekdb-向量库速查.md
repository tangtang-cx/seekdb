# seekdb / OceanBase 向量库速查（本文为团队实测整理）

> 结论来源：本仓库 `stepfun/tools/verify_seekdb_contract.py` 在真实 seekdb 内核上跑通的语句，
> 以及 `stepfun/server/seekdb-store.mjs` 通过 seekdb-js 生成的集合定义。

## 1. 集合（表）定义

seekdb 的一个「集合」在 SQL 层就是一张带 **全文索引** 和 **向量索引** 的表：

```sql
CREATE TABLE `browser_knowledge_base` (
  id VARBINARY(512) PRIMARY KEY NOT NULL,
  document STRING,
  embedding VECTOR(512),
  metadata JSON,
  FULLTEXT INDEX idx_fts (document) WITH PARSER ik PARSER_PROPERTIES=(ik_mode='smart'),
  VECTOR INDEX idx_vec (embedding) WITH(distance=cosine, type=hnsw, lib=vsag,
       m=16, ef_construction=200, ef_search=64)
) ORGANIZATION = HEAP
```

要点：

- `VECTOR(n)` 是原生向量列，`n` 是维度，必须与 embedding 模型输出维度一致。
- `FULLTEXT INDEX ... WITH PARSER ik` 使用 IK 中文分词器，`ik_mode='smart'` 为智能分词。
- `VECTOR INDEX ... WITH(distance=..., type=hnsw, lib=vsag, ...)` 定义 HNSW 近似最近邻索引，
  `lib=vsag` 指定使用 VSAG 向量检索库。
- `m` 是图的出度（越大召回越高、内存越大），`ef_construction` 是建图时的候选集大小，
  `ef_search` 是查询时的候选集大小（越大召回越高、延迟越高）。
- `ORGANIZATION = HEAP` 控制行存组织方式。

## 2. 写入

向量列用字面量数组插入，元数据用 `CAST(... AS JSON)`：

```sql
INSERT INTO `browser_knowledge_base` (id, document, metadata, embedding) VALUES
  (CAST('doc-hybrid' AS BINARY),
   '混合检索会同时执行向量检索与全文检索，再用 RRF 融合两路排名。',
   CAST('{"title": "混合检索", "source": "check"}' AS JSON),
   [0.10,0.20,0.30,0.40]);
```

## 3. 向量检索距离度量

`distance` 参数支持常见的距离度量：

| 写法 | 含义 | 备注 |
| --- | --- | --- |
| `cosine` | 余弦距离 | 与归一化 embedding 配合最常用，本项目默认 |
| `l2` | 欧氏距离 | 需保证各维同量纲 |
| `inner_product` | 内积 | 归一化向量下与余弦单调等价 |

**归一化很重要**：本项目用 bge-small-zh-v1.5 输出并做 L2 归一化后，
余弦距离与内积排序一致，评测结果可复现。

## 4. 索引刷新

HNSW 索引是异步构建的，写入后需要刷新，新文档才可被近似检索命中：

```sql
CALL dbms_index_manager.refresh();
```

seekdb-js 封装为 `collection.refresh_index()`。**忘记刷新**是「明明写进去了却查不到」
最常见的原因。

## 5. 容量与维度经验值

| 场景 | 维度 | m | ef_construction | ef_search |
| --- | --- | --- | --- | --- |
| 小规模演示（< 10 万） | 512 | 16 | 200 | 64 |
| 百万级召回优先 | 768/1024 | 32 | 400 | 128 |
| 高并发低延迟 | 512 | 16 | 200 | 32 |

维度越高内存与建图时间线性上升；`ef_search` 建议在 `[32, 256]` 之间按召回压测调参。
