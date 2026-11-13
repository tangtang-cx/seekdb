# 数据库代码审查规则集（15 条）

规则的实现见 `reviewer.py` 的 `RULES` 列表，编号与下表一致。
静态规则完全离线、确定性可复现；大模型审查在 `app.py` 中作为第二层叠加。

| 编号 | 级别 | 标题 | 判定方式 | 修复建议 |
| --- | --- | --- | --- | --- |
| OB-001 | 🔴 阻断 | UPDATE / DELETE 缺少 WHERE | 正则匹配 `update`/`delete from` 后无 `where` | 补 WHERE；先 SELECT 校验影响行数 |
| OB-002 | 🔴 阻断 | JOIN 缺少关联条件 | `join` 后无 `on`/`using` | 补 ON，确认两侧类型一致 |
| OB-003 | 🔴 阻断 | 建表缺少主键 | `create table` 语句块内无 `primary key` | 加 PRIMARY KEY，避免随机 UUID 主键 |
| OB-004 | 🟠 警告 | SELECT \* | `select *` | 显式列出列，减少 IO 与回表 |
| OB-005 | 🟠 警告 | LIKE 前置通配符 | `like '%...'` | 改前缀匹配或走全文索引 |
| OB-006 | 🟠 警告 | 索引列被函数包裹 | WHERE 中对列用 `year()/date_format()/substring()/lower()` 等 | 改范围条件，或建函数索引/生成列 |
| OB-007 | 🟠 警告 | 深分页 OFFSET | `offset >= 10000` 或 `limit n, m` 中 m ≥ 10000 | 游标分页 `WHERE id > last_id` |
| OB-008 | 🟠 警告 | NOT IN / != 与 NULL | `not in (`、`!=`、`<>` | 改 NOT EXISTS，列设 NOT NULL |
| OB-009 | 🟠 警告 | IN 列表过长 | `in (` 内逗号数 ≥ 50 | 改 JOIN 临时表或分批 |
| OB-010 | 🟠 警告 | SELECT ... FOR UPDATE 无 WHERE | `for update` 后无 `where` | 缩小锁范围，缩短事务 |
| OB-011 | 🔵 提示 | UNION 去重开销 | `union`（不含 `union all`） | 不需要去重改 `UNION ALL` |
| OB-012 | 🔵 提示 | TRUNCATE 清表 | `truncate [table]` | 需回滚用 DELETE；接受 DDL 语义再用 TRUNCATE |
| OB-013 | 🔵 提示 | 缺少执行计划验证 | 语句以 `select`/`with` 开头 | 用 `EXPLAIN` / `EXPLAIN FORMAT=JSON` 确认命中索引 |
| OB-014 | 🔵 提示 | 疑似隐式类型转换 | `where` 中 `列 = 数字` | 字面量类型与列类型一致 |
| OB-015 | 🔵 提示 | COUNT(1) vs COUNT(*) | `count(1)` | 统一 `COUNT(*)`，现代优化器下等价 |

## 规则设计原则

1. **确定性优先**：能用正则判定的绝不让模型判，减少误报、保证可复现、可进 CI。
2. **误报可解释**：每条规则给出「问题 + 建议 + 命中片段」，评审人一眼能判断是否真命中。
3. **分级**：error（可能造成数据错误或全表影响）、warn（性能/可维护性风险）、info（风格与最佳实践）。
4. **引擎无关**：规则只依赖标准 SQL 语义，OceanBase（MySQL 模式）、seekdb、MySQL 8 通用。

## OceanBase / seekdb 专属补充建议（大模型层负责）

- 向量检索建表必须显式声明 `VECTOR(n)` 维度，并与 embedding 模型输出一致。
- HNSW 索引参数 `m` / `ef_construction` / `ef_search` 需要压测确定，别照抄默认值。
- 写入后需要 `CALL dbms_index_manager.refresh()`（或 seekdb-js 的 `refresh_index()`），
  否则新向量查不到。
- 大表 DDL 优先走 Online DDL（OceanBase 支持 `ALTER TABLE ... ALGORITHM=INSTANT/INPLACE`），
  避免长时间锁表。
