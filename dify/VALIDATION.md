# Dify 赛题 · 验证样例（VALIDATION.md）

> **本文档描述的是可选增强，不是评测对象。**
> 主交付是 `app.yml`（workflow：开始 → 规则体检 code 节点 → 出方），
> **不需要 seekdb、不需要模型、不需要外部服务**。下面这套 seekdb 检索增强
> 只在你想看「真·向量检索」时使用，评测时可以完全忽略。

> 每组样例包含：初始条件 → 输入 → 操作步骤 → 预期表现 → 复核命令。
> 评审可逐组执行；每组都能独立复现。

## 样例 A：慢查询 + 深分页（核心玩法）

**初始条件**：应用已启动（`streamlit run app.py`）；无需预置数据。

**输入**：

```sql
SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01'
  AND o.status IN ('NEW', 'PAID', 'SHIPPED', 'DONE')
  AND c.city LIKE '%杭州%'
ORDER BY o.created_at DESC
LIMIT 20, 200000;
```

**操作步骤**：粘贴 → 点「🚀 开始审查」。

**预期表现**（六段齐全、顺序不变）：

| 段 | 预期内容 |
| --- | --- |
| 📖 医书摘录 | 引用《OceanBase / seekdb 医书》中与「函数包裹索引列 / 深分页 / SELECT \*」相关的条目（接了 seekdb 时来自真实检索结果） |
| 🩺 望闻问切 | ≥3 条：`SELECT *` 全列回表；`DATE(col)` 使索引失效；`LIMIT 20, 200000` 深分页扫描并丢弃行 |
| 💊 药方 | 显式列 + `created_at >= '2026-01-01' AND created_at < '2026-01-02'` + 游标分页 `WHERE o.id > :last_id ORDER BY o.id LIMIT 100`（可复制执行） |
| 🚫 忌口 | 不要在索引列套函数；不要大 OFFSET |
| 🧘 养生建议 | 给 `orders(created_at)` 建索引，必要时用覆盖索引带上排序列 |
| 🎋 医嘱小笺 | 俏皮话 + 点出最该先改的那处 |

**复核（seekdb 真的在起作用）**：

```bash
python seekdb_service/verify.py     # 4 个问题全部命中；plan 含 _fts + _vs 双分支
curl http://127.0.0.1:8848/health  # chunks=19
```

## 样例 B：全表更新（阻断级）

**输入**：`UPDATE orders SET status = 'ARCHIVED';`
**预期**：命中 **OB-001**（更新/删除缺 WHERE），药方给出带 WHERE 的改写与影响行数确认语句。

## 样例 C：向量库建表 DDL（不应误报）

**输入**：

```sql
CREATE TABLE doc_chunk (
  id VARBINARY(512) PRIMARY KEY NOT NULL,
  document STRING,
  embedding VECTOR(512),
  FULLTEXT INDEX idx_fts (document) WITH PARSER ik PARSER_PROPERTIES=(ik_mode='smart'),
  VECTOR INDEX idx_vec (embedding) WITH(distance=cosine, type=hnsw, lib=vsag,
       m=16, ef_construction=200, ef_search=64)
) ORGANIZATION = HEAP;
```

**预期**：**不**命中 OB-003（建表缺主键）；提醒写入向量后需 `CALL dbms_index_manager.refresh()`。

## 样例 D：无模型环境仍可跑

**初始条件**：Dify 工作区未配置任何模型供应商；导入 `app-nomodel.yml`。

**输入**：同样例 A。
**预期**：仍然输出**固定六段**，并逐条对照 15 条规则给出结论（不依赖模型）。

## 样例 E：项目自启动与持久化

```bash
python smoke_test.py                                   # PASS：启动 + 探活
docker compose -f deploy/docker-compose.yml up -d     # 带卷的 seekdb
docker compose -f deploy/docker-compose.yml restart seekdb knowledge-service
sleep 30 && curl http://127.0.0.1:8848/health         # chunks 仍是 19（不是 0）→ 持久化生效
```

## 恢复初始状态

样例 A~D 都是**只读**的（不写入数据），重复执行结果一致。
样例 E 会重新灌一次知识库（19 块，幂等）。
