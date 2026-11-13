# 混合检索（向量 + 全文）与 RRF 融合

> 结论来源：`stepfun/tools/verify_seekdb_contract.py`，该脚本在真实 seekdb 内核上验证了
> `DBMS_HYBRID_SEARCH.GET_SQL` 能生成可执行计划，且计划中同时包含全文分支与向量分支。

## 1. 为什么需要混合检索

- **向量检索**擅长语义相近但用词不同的问题（"怎么让查询更快" vs "如何优化检索性能"）。
- **全文检索**擅长精确匹配（错误码、表名、函数名、专有名词）。
- 只用向量会漏掉精确关键字；只用全文会漏掉同义表达。生产检索系统通常两路召回再融合。

## 2. RRF（Reciprocal Rank Fusion）

RRF 只用排名不用分数：

```text
score(d) = Σ_over_rankers 1 / (k + rank_i(d))     # 常数 k 通常取 60
```

优点：向量分（余弦距离）和 BM25 分量纲完全不同，直接加权需要归一化且不稳定；
RRF 只依赖名次，天然跨检索器可比。本项目在 seekdb 内核内完成融合，**不是**客户端取两路再拼。

## 3. `@search_parm` 协议

seekdb 通过一个 JSON 变量 `@search_parm` 描述混合检索请求，
再由 `DBMS_HYBRID_SEARCH.GET_SQL` 把它翻译成可执行 SQL：

```json
{
  "query": { "query_string": { "fields": ["document"], "query": "混合检索" } },
  "knn":   { "field": "embedding", "k": 5, "query_vector": [0.11,0.21,0.31,0.41] },
  "rank":  { "rrf": {} },
  "size":  5
}
```

字段含义：

| 字段 | 说明 |
| --- | --- |
| `query.query_string` | 全文分支：检索字段列表 + 查询串（走 IK 分词） |
| `knn.field` | 向量分支：向量列名 |
| `knn.k` | 向量分支召回条数 |
| `knn.query_vector` | 查询向量字面量数组，维度必须与列定义一致 |
| `rank.rrf` | 融合方式，`{}` 表示使用默认 k 常数的 RRF |
| `size` | 融合后返回条数 |

调用方式：

```sql
SET @search_parm = '{"query":{"query_string":{"fields":["document"],"query":"混合检索"}}, ...}';
SELECT DBMS_HYBRID_SEARCH.GET_SQL('browser_knowledge_base', @search_parm) as query_sql FROM dual;
-- 再执行上一步返回的 query_sql
```

## 4. 单分支也能用同一套协议

只要不传另一分支即可单独使用：

```sql
-- 只走全文
SET @search_parm = '{"query":{"query_string":{"fields":["document"],"query":"混合检索"}},"size":5}';
-- 只走向量
SET @search_parm = '{"knn":{"field":"embedding","k":5,"query_vector":[0.91,0.81,0.71,0.61]},"size":5}';
```

## 5. JavaScript 侧写法（seekdb-js）

```js
const result = await collection.hybridSearch({
  query: { whereDocument: { $contains: query }, nResults: candidateCount },
  knn:   { queryEmbeddings: [embedding], nResults: candidateCount },
  rank:  { rrf: {} },
  nResults: limit,
  include: ["documents", "metadatas", "distances"],
});
```

`whereDocument.$contains` 对应全文分支，`queryEmbeddings` 对应向量分支，
`rank.rrf` 触发内核内 RRF 融合。

## 6. 工程注意事项

1. **先刷新索引再检索**：`CALL dbms_index_manager.refresh();`，否则新写入的向量查不到。
2. **两路召回数要放大**：融合前每路取 `3 * top_k` 以上，避免融合后候选不足。
3. **维度一致性**：查询向量维度必须等于 `VECTOR(n)` 的 n，否则计划执行报错。
4. **空结果兜底**：全文分支可能零命中（如关键词全为停用词），应在 UI 上提示
   "未检索到关键词命中，仅返回向量近似结果"。
