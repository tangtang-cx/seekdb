# Qoder 赛题 · 验证样例（VALIDATION.md）

> **第 0 步：主功能自检**（零依赖，任何装了 Python 3.9+ 的机器都能跑，数秒结束、退出码 0）：
>
> ```bash
> cd qoder
> python run.py            # -> SELFCHECK PASS (4/4 用例, 15 条规则)
> ```
>
> **第 1 步：起服务做交互复核**（下面每个样例都可以用 `curl` 直接验，预期输出与实际运行**逐字一致**）：
>
> ```bash
> python run.py --serve    # 或 bash start.sh --serve   ->  http://127.0.0.1:8501
> ```

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

**预期**：`{"ok": true, "app": "qoder-review-assistant", "rules_loaded": 15, "seekdb": {...}}`（HTTP 200）。

## 样例 D：seekdb 实际作用（需先装 requirements-seekdb.txt）

```bash
pip install -r requirements-seekdb.txt
python seekdb_service/fetch_model.py        # bge-small-zh INT8 权重（约 23 MiB）
python seekdb_service/capture_evidence.py   # 在真内核上跑一遍并写出 EVIDENCE_ROOT.json
```

**预期输出**：

```text
evidence written to .../Qoder/EVIDENCE_ROOT.json
rule knowledge chunks: 15, review rows: 1
  深分页 OFFSET 太大怎么办？ -> 3 hits (fulltext=True, vector=True)
  WHERE 里的列被函数包裹会导致索引失效吗？ -> 3 hits (fulltext=True, vector=True)
  SELECT * 有什么问题，应该怎么改写？ -> 3 hits (fulltext=True, vector=True)
  NOT IN 和 NULL 组合会漏掉哪些行？ -> 3 hits (fulltext=True, vector=True)
```

`EVIDENCE_ROOT.json` 里可核对：`engine=seekdb` / `mode=embedded`、两张表的真实 DDL、
写入行数（规则知识 15 条、审查历史 1 行）、每次检索的 `plan_has_fulltext_branch` 与
`plan_has_vector_branch` **同时为 true**（说明检索计划里既有全文分支也有向量分支）、
命中的原文片段与 `review_log_id`。

未装 `pylibseekdb` 时主功能不受影响（`run.py` 仍 `SELFCHECK PASS`，输出 `[seekdb] SKIP`）。

## 样例 E：审查确实走 seekdb（读 + 写）

```bash
python run.py --serve
curl -s -X POST localhost:8501/api/review -H "Content-Type: application/json" \
  -d "{\"sql\": \"UPDATE orders SET status = 'ARCHIVED';\"}"
```

**预期**：响应里除 `findings` / `summary` 外还有

- `seekdb`：`{"available": true, "engine": "seekdb", "mode": "embedded", "rule_knowledge_rows": 15, "review_log_rows": 1, "embedding": {"model": "bge-small-zh-v1.5 (INT8 ONNX)", "fallback": false}}`
- `review_id`：本轮审查写入 `qoder_review_log` 的记录 id
- 每条 finding 的 `basis`：由 seekdb 混合检索取回的判定依据（`rule_id` 与问题编号一致）

再查一次 `/health`，`seekdb.review_log_rows` 会 +1 —— 这是「指定技术实际发挥作用」的可核对记录。

## 样例 F：数据能写进去、也能读回来（记忆复用）

```bash
python run.py                # 自检末尾：[memory] PASS ... 写入 0 -> 1（子进程写）
python run.py --readback     # 另一个进程读回
```

**预期**：

```text
[memory] PASS  sqlite 后端：规则知识 15 条；审查记录 0 -> 1（写入 id ...）；sqlite 后端：读回 1 条审查记录
...
READBACK PASS (读回 N 条审查记录)
```

`--readback` 输出的 JSON 里含 `stats`（后端、知识条数、审查条数、sqlite 文件路径）、
`reviews`（最近写进去的审查记录）、`knowledge_sample`（从记忆里检索回来的规则知识）。
服务模式下同样可以 `curl -s localhost:8501/api/memory`。

写入位置：真 seekdb 内核的 `qoder_review_log` 表 + 始终存在的 sqlite 镜像 `data/memory.db`
（随仓库分发，clone 下来就有 15 条规则知识）。即使评测机没有 `pylibseekdb`，
读回依然成立 —— 数据在磁盘上，不在内存里。

## 自检

```bash
python tests/test_rules.py -v      # 23 passed
```
