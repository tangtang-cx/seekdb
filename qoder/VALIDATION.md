# Qoder 赛题 · 验证样例（VALIDATION.md）

> **先起服务**（零依赖，任何装了 Python 3.9+ 的机器都能跑）：
>
> ```bash
> cd qoder
> bash start.sh            # 或 python3 run.py   ->  http://127.0.0.1:8501
> ```
>
> 下面的每个样例都可以用 `curl` 直接复核，预期输出与实际运行**逐字一致**。

## 样例 A：慢查询 + 深分页（核心玩法）

**输入**：

```sql
SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01'
  AND o.status IN ('NEW', 'PAID', 'SHIPPED', 'DONE')
  AND c.city LIKE '%杭州%'
ORDER BY o.created_at DESC
LIMIT 20, 200000;
```

**操作**：界面粘 SQL → 点「开始审查」；或命令行：

```bash
curl -s -X POST localhost:8501/api/review -H "Content-Type: application/json" \
  -d "{\"sql\": \"SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id WHERE DATE(o.created_at) = '2026-01-01' AND c.city LIKE '%杭州%' ORDER BY o.created_at DESC LIMIT 20, 200000;\"}"
```

**预期（实测输出）**：`summary = {"error": 0, "warn": 4, "info": 1}`，命中 5 条：

| 规则 | 级别 | 标题 |
| --- | --- | --- |
| OB-004 | 🟠 警告 | SELECT * 列出全部列 |
| OB-005 | 🟠 警告 | LIKE 前置通配符 |
| OB-006 | 🟠 警告 | 索引列被函数包裹 |
| OB-007 | 🟠 警告 | 深分页 OFFSET |
| OB-013 | 🔵 提示 | 缺少执行计划验证 |

每条 finding 都带 `message`（问题）、`suggestion`（改法）、`snippet`（命中片段）。
**把 `DATE(o.created_at)` 改成 `o.created_at >= '2026-01-01'` 后重跑，OB-006 消失**——证明结果由输入决定，不是写死的。

## 样例 B：全表更新（阻断级）

**输入**：`UPDATE orders SET status = 'ARCHIVED';`

**预期（实测输出）**：`summary = {"error": 1, "warn": 0, "info": 0}`，仅命中：

| 规则 | 级别 | 标题 |
| --- | --- | --- |
| OB-001 | 🔴 阻断 | UPDATE / DELETE 缺少 WHERE |

## 样例 C：健康检查

**输入**：`curl -s localhost:8501/health`

**预期**：`{"ok": true, "app": "qoder-review-assistant", ...}`（HTTP 200）。

## 样例 D：seekdb 实际作用（可选增强，需先装 requirements-seekdb.txt）

```bash
python seekdb_service/verify.py
```

**预期**：真 seekdb 内核启动、知识库写入并做向量+全文混合检索，返回命中文档与分数
（这是「seekdb 实际发挥作用」的核对记录；不装 seekdb 时主功能不受影响）。

## 自检

```bash
python tests/test_rules.py -v      # 23 passed
```
