# Qoder 赛题 · 验证样例（VALIDATION.md）

> 每组样例包含：初始条件 → 输入 → 操作步骤 → 预期表现 → 复核命令。

## 样例 A：慢查询 + 深分页（核心玩法）

**初始条件**：`cd qoder && pip install -r requirements.txt && streamlit run app.py`，浏览器打开 <http://localhost:8501>。

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

**预期表现**：

| 指标 / 区块 | 预期 |
| --- | --- |
| 🔴 阻断 | 0 条 |
| 🟠 警告 | 3 条：`OB-004`（SELECT \*）、`OB-006`（索引列被函数包裹：DATE()）、`OB-007`（深分页 OFFSET） |
| 🔵 提示 | ≥1 条（`OB-013` 缺执行计划验证 / `OB-014` 隐式类型转换） |
| 📖 seekdb 检索到的依据 | 展开后可见来自 `dify_knowledge_base` 的原文（向量 + 全文 + RRF 命中） |
| 写入 seekdb | 页面出现「本轮审查已写入 seekdb（记录 id …）」 |
| 🗂️ 历史 | 展开后可见刚写入的那条（severity=warn） |

**复核**：

```bash
curl http://127.0.0.1:8848/reviews   # 能查到刚写入的审查记录
python seekdb_service/verify.py      # 4 个问题真实命中，plan 含 _fts + _vs
```

## 样例 B：全表更新（阻断级）

**输入**：`UPDATE orders SET status = 'ARCHIVED';`
**预期**：🔴 1 条 `OB-001`（UPDATE / DELETE 缺少 WHERE），药方给出带 WHERE 的改写。

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

**预期**：不出现 `OB-003`（建表缺主键）；提示「写入后需 `CALL dbms_index_manager.refresh()`」。

## 样例 D：重复输入与边界

| 操作 | 预期 |
| --- | --- |
| 同一段 SQL 连点两次 | 结果一致；历史里按轮次追加两条，不产生脏数据 |
| 输入空内容 | 提示「先贴点病历进来。」，不报错 |
| 输入非 SQL 文本 | 仍返回结构化结果，不崩溃 |
| 关掉 seekdb 服务后审查 | 侧边栏提示「seekdb 未就绪：…」，**审查照常返回**（降级不崩） |
| 模型 Key 无效 / 超时 | 捕获并提示「模型调用失败：…」，seekdb 已检索到的依据照常展示 |
| 两个浏览器窗口同时审查 | 各自独立，互不干扰（服务由服务端统一管理） |

## 样例 E：自启动与持久化

```bash
python smoke_test.py                                    # PASS
docker compose --profile seekdb up -d
docker compose --profile seekdb restart seekdb knowledge-service
sleep 30 && curl http://127.0.0.1:8848/health          # chunks 仍是 19 → 持久化生效
```

## 恢复初始状态

样例 A~D 均为只读操作（唯一写入是审查历史，可随时清空 seekdb 的 `qoder_review_log` 表）；
样例 E 会重新灌一次知识库（19 块，幂等）。
