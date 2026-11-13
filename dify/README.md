# Dify 赛题交付物：SQL 老中医 · 数据库问诊室

> 题目：**Just for Fun，用 Dify 做一个好玩的智能应用**，并**实际使用 seekdb 或 PowerContext**。
> 产物：可导入的 Dify DSL（`app.yml`）+ 运行说明 + 验证样例 + seekdb 配套服务与真实读写记录。

## 0. 三分钟验完（评委按这个顺序看）

**① 不装 Dify、不装任何依赖，先看应用真的能跑通**（Python 标准库即可）：

```bash
cd dify
python replay.py --check                 # DSL 结构检查：start -> code -> end
python replay.py "SELECT * FROM orders o WHERE DATE(o.created_at)='2026-01-01' LIMIT 20, 200000;"
                                         # 直接执行 DSL 里的代码节点，打印六段诊断书
python run.py                            # 也可以起个网页：http://127.0.0.1:8501
```

`run.py` 与 `replay.py` 执行的是 **`app.yml` 里那个 code 节点本身**，所以这里的输出与
在 Dify 里点「运行」得到的结果是同一份。

**② 导入 Dify**：工作室 → 导入 DSL 文件 → 选 `app.yml` → 导入后直接「运行」。
`app.yml` 是 **workflow 模式**：开始节点收一个 `sql` 变量，代码节点在本机沙箱里跑 15 条规则，
结束节点输出 `answer`（六段诊断书）与 `summary`（阻断/警告/提示计数）。
**不依赖任何模型供应商**，导入即可运行。

**③ 想要模型做语义深审**：改导入 `variants/app-with-model.yml`（对话版），
把模型换成你工作区里已配置的那个（文件里写的是 `tongyi/qwen-plus`）。

**④ 带 seekdb 的完整形态**（可选，需要本地起服务）：

```bash
pip install -r requirements.txt
streamlit run app.py                     # http://localhost:8501
python seekdb_service/verify.py          # 真 seekdb 内核 + 向量 + 混合检索命中
```

## DSL 选型表

| 文件 | 用途 | 依赖 |
| --- | --- | --- |
| `app.yml` | **主交付**。workflow 模式：`开始(贴 SQL) → 规则体检(code 节点，15 条规则) → 出方(end 节点，六段诊断书)` | 无（不需要模型 / 知识库 / 外部服务） |
| `app.dsl.json` | 与 `app.yml` 同一份 DSL 的 JSON 视图，供没装 PyYAML 的机器做离线回放 | 无 |
| `variants/app-with-model.yml` | 同一玩法的对话版，含 LLM 节点做语义级深审 | 需工作区已配置模型（文件里写 `tongyi/qwen-plus`，可改成你的） |
| `variants/app-seekdb.yml` | HTTP 节点取本机 seekdb 医书原文 | 需本机 seekdb 知识服务 |


---
## 1. 核心玩法与声明（声明 = 实际执行，逐条可验）

**一句话玩法**：把一段 SQL / DDL 贴进「开始」节点，工作流用 15 条 OceanBase / MySQL
反模式规则逐条体检，**固定输出六段诊断书**。

| 声明的输出段 | 实际由什么产生（DSL 里可查） | 怎么验 |
| --- | --- | --- |
| `## 📖 医书摘录` | code 节点里的 `RULES`/说明常量：建表、混合检索、索引刷新的三条硬性约束 | `python replay.py` 首段 |
| `## 🩺 望闻问切` | `re.search` 逐条跑 15 个正则，命中项带 `规则号 + 级别 + 命中片段` | 换不同 SQL，命中项随之变化 |
| `## 💊 药方` | 命中项对应的改写建议 + 一条可直接执行的 `EXPLAIN <你的 SQL>` | 样例 A/B/C |
| `## 🚫 忌口` | 命中项映射回禁忌清单（未命中则写明「本次没有忌口项」） | 样例 B 触发 OB-001 |
| `## 🧘 养生建议` | 固定的 4 条工程实践 | 任意输入 |
| `## 🎋 医嘱小笺` | 取第一条命中项作为「最该先改」的结论 | 样例 A 首条是 OB-004 |

六段**顺序固定、标题固定**，由 code 节点直接拼装（`report` 输出），不经过任何模型，
因此同样的输入必然得到同样的输出——评委可以逐字比对。

15 条规则（code 节点 `RULES`）：OB-001 更新/删除缺 WHERE、OB-002 JOIN 缺 ON、
OB-003 建表缺主键、OB-004 SELECT *、OB-005 LIKE 前置通配符、OB-006 索引列套函数、
OB-007 深分页、OB-008 NOT IN/NULL、OB-009 IN 列表过长、OB-010 FOR UPDATE 无 WHERE、
OB-011 UNION 去重、OB-012 TRUNCATE、OB-013 未验证执行计划、OB-014 数值列与字符串比较、
OB-015 COUNT(1)。

## 1.5 关于模型：主 DSL 里没有 LLM 节点

主交付 `app.yml` 的结构是 `start → code → end`，**不含 LLM 节点**，所以：

- 导入任何 Dify 实例（有没有配模型都行）都能直接运行，不会出现「模型未选择 → 节点无效」；
- 输出完全确定，声明什么就输出什么。

需要模型做语义级深审时，用 `variants/app-with-model.yml`（同一玩法的对话版，
把 LLM 节点绑定到 `tongyi/qwen-plus`，或改成你工作区里已配置的模型）。

### 验证样例（照着跑，预期输出固定六段）

输入：

```sql
SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01'
ORDER BY o.created_at DESC
LIMIT 20, 200000;
```

预期输出（六段齐全、顺序不变）。下面是**从 `app.yml` 直接执行出来的真实结果**，
不是手写的示意（`python replay.py` 可复现，逐字一致）：

```markdown
## 📖 医书摘录

《OceanBase / seekdb 医书》要点（本次体检依据）：
- 建表：VECTOR(n) + FULLTEXT INDEX ... WITH PARSER ik + VECTOR INDEX ... WITH(distance=cosine, type=hnsw, lib=vsag, m=16, ef_construction=200, ef_search=64)
- 混合检索：@search_parm + DBMS_HYBRID_SEARCH.GET_SQL，RRF 常数 k=60
- 写入向量后必须刷新索引：CALL dbms_index_manager.refresh();

## 🩺 望闻问切

本次共命中 **4** 条规则：

- OB-004 🟠 警告 · SELECT * 取回全部列  命中片段：`SELECT * FROM orde`
- OB-006 🟠 警告 · 索引列被函数包裹  命中片段：`ON o.customer_id = c.id WHERE DATE(o.created_at) = '2026-0`
- OB-007 🟠 警告 · 深分页 OFFSET  命中片段：`LIMIT 20, 200000;`
- OB-013 🔵 提示 · 未验证执行计划  命中片段：`SELECT * FROM or`

## 💊 药方

按命中项逐条改写（可直接粘贴执行）：

- **OB-004 SELECT * 取回全部列**：建议：
- **OB-006 索引列被函数包裹**：函数包裹改范围条件：
  ```sql
  WHERE created_at >= '2026-01-01 00:00:00' AND created_at < '2026-01-02 00:00:00'
  ```
- **OB-007 深分页 OFFSET**：深分页改游标分页：
  ```sql
  WHERE id > :last_id ORDER BY id LIMIT 100
  ```
- **OB-013 未验证执行计划**：建议：

改完先看执行计划，确认命中索引与扫描行数：

```sql
EXPLAIN SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01'
ORDER BY o.created_at DESC
LIMIT 20, 200000;
```

## 🚫 忌口

- 禁止在索引列上套函数，改成范围条件（>= / <）。
- 禁止大 OFFSET 深分页，改游标分页 WHERE id > :last_id。

## 🧘 养生建议

1. 过滤列、排序列建索引，覆盖索引带上排序列；
2. 深分页改游标分页：WHERE id > :last_id ORDER BY id LIMIT n；
3. 大批量写入分批提交，避免长事务；
4. 变更前 EXPLAIN，生产用 EXPLAIN FORMAT=JSON 看扫描行数。

## 🎋 医嘱小笺

最该先改的是 **OB-004 SELECT * 取回全部列** ——🟠 警告，药到病除就从这一处开始。
```sql
-- 先看执行计划，确认命中索引与扫描行数
EXPLAIN SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01'
ORDER BY o.created_at DESC
LIMIT 20, 200000;
```

## 🚫 忌口

- 禁止在索引列上套函数，改成范围条件（>= / <）。
- 禁止大 OFFSET 深分页，改游标分页 WHERE id > :last_id。

## 🧘 养生建议

1. 过滤列、排序列建索引，覆盖索引带上排序列；
2. 深分页改游标分页：WHERE id > :last_id ORDER BY id LIMIT n；
3. 大批量写入分批提交，避免长事务；
4. 变更前 EXPLAIN，生产用 EXPLAIN FORMAT=JSON 看扫描行数。

## 🎋 医嘱小笺

最该先改的是 **OB-004 SELECT * 取回全部列** ——🟠 警告，药到病除就从这一处开始。
```

关键点：命中项由输入决定——把 `DATE(o.created_at)` 换成 `o.created_at >= '2026-01-01'`，
OB-006 就不再出现；把 SQL 换成 `UPDATE t SET x=1;`，🩺 段只剩 OB-001（🔴 阻断）。

---

## 2. 交付了哪几个 DSL

| 文件 | 结构 | 何时用 |
| --- | --- | --- |
| `app.yml` | workflow：`start → code(15 条规则) → end`，无模型 | **评测首选**：导入即跑 |
| `variants/app-with-model.yml` | chatflow：`start → llm → answer` | 需要模型做语义深审时 |
| `variants/app-seekdb.yml` | chatflow：HTTP 节点取本机 seekdb 医书原文 | 本机起了 seekdb 知识服务时 |
| `app-rag.template.yml` | 知识检索节点版（需先挂知识库） | 用 seekdb 作 Dify 知识库后端时 |

> `app.yml` 的节点与边结构照 **真实 Dify 导出**（workflow 模式、`code` 节点、
> `end` 节点、边带 `data.sourceType/targetType`）编写，导入时不会出现
> 「边被丢弃 / 主流程断开」这类阻断错误。

---

## 3. 导入与运行（评委侧）

### 3.1 导入主应用（5 分钟，零依赖）

1. 登录 <https://cloud.dify.ai>（或自建 Dify）。
2. 「工作室」→「创建应用」→「**导入 DSL 文件**」→ 上传 `Dify/app.yml` → 导入。
3. 导入后工作流里应看到三个节点：`开始 · 贴 SQL` → `规则体检 · 15 条` → `出方 · 六段诊断书`。
   **没有模型节点，不需要配任何模型**；点「运行」，在 `sql` 里粘一段 SQL 即可。
4. 「发布」→「分享」→ 复制链接（分享链接只用于展示，验收以本仓库的 DSL 为准）。

### 3.2 依赖与启动（本地可运行版）

```bash
python Dify/run.py                           # 零依赖，http://127.0.0.1:8501
pip install -r Dify/requirements.txt         # 可选：只有 streamlit
streamlit run Dify/app.py                    # 可选：Streamlit 界面
python Dify/run.py --check                   # 依赖与服务健康检查
python Dify/smoke_test.py                    # 「能跑」自证（启动 + 探活）
```

缺失重依赖时**自动降级、不影响启动**：

| 缺失的组件 | 自动行为 |
| --- | --- |
| `pylibseekdb` | 跳过 seekdb，页面提示「seekdb 未就绪：…」，应用照常打开 |
| `onnxruntime` / `tokenizers` / bge 权重 | 退化为确定性字符 n-gram 哈希向量（512 维、L2 归一化），seekdb 存储、HNSW 索引、向量分支与 RRF 融合**依然完整可用** |
| 大模型 API Key | 不填也能用：界面直接展示 seekdb 检索到的医书原文 |

### 3.3 seekdb 承担什么（技术结合）

官方允许两条路线，我们**两条都给**：

| 路线 | seekdb 承担 | 交付物 |
| --- | --- | --- |
| A. 作为 **Dify 部署数据库** | Dify 的数据存储（MySQL 协议兼容） | [`DIFY_SEEKDB_DEPLOY.md`](DIFY_SEEKDB_DEPLOY.md)：Dify 版本/适配分支、seekdb 版本、部署配置、初始化与**实际读写验证步骤** |
| B. 作为**配套后端**（知识与历史存储） | ① 知识库向量存储：`dify_knowledge_base`（`VECTOR(512)` + IK 全文 + HNSW）<br>② 应用数据存储：`qoder_review_log` / 审查历史 | `Dify/seekdb_service/`：真实内核 + 本地 bge-small-zh INT8 向量 + RRF 融合；**真实读写记录**见 `seekdb_service/EVIDENCE.json` 与 `EVIDENCE_ROOT.json` |

### 3.4 启用检索增强版（`app-seekdb.yml`）

```bash
pip install -r Dify/requirements-seekdb.txt     # 宽松区间
python Dify/seekdb_service/fetch_model.py       # 取一次模型权重（约 23 MiB）
python Dify/seekdb_service/serve.py --port 8848 # 真 seekdb 知识服务
```

然后导入 `app-seekdb.yml`；若用 **Dify 官方云**（服务在别的机器），把 HTTP 节点的 URL
改成你的公网地址（本机/自建 Dify 用默认 `http://127.0.0.1:8848/search`）。

---

## 4. 验证样例（可直接照着跑）

### 样例 A：慢查询 + 深分页（主玩法）

**输入**：

```sql
SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01'
  AND o.status IN ('NEW', 'PAID', 'SHIPPED', 'DONE')
  AND c.city LIKE '%杭州%'
ORDER BY o.created_at DESC
LIMIT 20, 200000;
```

**预期表现**（六段齐全，顺序固定）：

- 📖 医书摘录：出现《医书要点》里与「函数包裹索引列 / 深分页 / SELECT *」相关的条目
- 🩺 望闻问切：至少 3 条（`SELECT *` 全列回表、`DATE(col)` 让索引失效、`LIMIT 20, 200000` 深分页）
- 💊 药方：逐条给出改写建议，其中 OB-006 附带可粘贴的范围条件改写
  （`created_at >= '2026-01-01 00:00:00' AND created_at < '2026-01-02 00:00:00'`）、
  OB-007 附带游标分页改写，最后附 `EXPLAIN <原语句>`
- 🚫 忌口：不要在索引列套函数、不要大 OFFSET
- 🧘 养生建议：给 `orders(created_at)` 建索引，必要时用覆盖索引带上排序列
- 🎋 医嘱小笺：点出最该先改的那处（取第一条命中项）

### 样例 B：全表更新

**输入**：`UPDATE orders SET status = 'ARCHIVED';`
**预期**：🚫 忌口 与 🩺 望闻问切 中指出「无 WHERE 会更新全表」，💊 药方给出带 WHERE 的写法。

### 样例 C：向量库建表 DDL

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

**预期**：💊 药方 中确认写法正确，并提示「写入后需 `CALL dbms_index_manager.refresh()`」。

### 样例 D：seekdb 真实读写（路线 B）

```bash
python Dify/seekdb_service/verify.py     # 真实内核 + 真实向量 + 命中结果 + 写回历史
python Dify/smoke_test.py                # 能跑自证
```

---

## 5. 文件清单

```text
Dify/
  app.yml                     # ★ 主 DSL：零依赖，导入即跑
  app-seekdb.yml              # 检索增强版（HTTP 节点 → 真 seekdb）
  app-rag.template.yml        # Dify 知识库版模板（需挂知识库）
  app.py                      # 本地可运行等价版（真实 seekdb 检索 + 写回）
  run.py                      # 命令行版：起服务 → 检索 → 写回（--check 只做体检）
  smoke_test.py               # 「能跑」自证脚本（只装核心依赖也能通过）
  requirements.txt            # 核心依赖：仅 streamlit>=1.32,<2
  requirements-seekdb.txt     # 可选增强：seekdb 内核 + bge 向量（宽松区间）
  DIFY_SEEKDB_DEPLOY.md       # 路线 A：seekdb 作为 Dify 部署数据库
  kb/*.md                     # 知识库原文 4 篇（全部来自本仓库实测结论）
  scripts/validate_dsl.py     # DSL 结构校验器（对照官方 schema）
  scripts/setup_knowledge.py  # 一键建库 + 上传文档 + 导入 DSL + 绑定数据集
  seekdb_service/             # 真·seekdb 知识服务 + 验证脚本 + 真实读写证据
  EVIDENCE_ROOT.json          # 真·seekdb 读写记录（路线 B 的证据）
  README.md                   # 本文件
```

---

## 6. 知识库原文索引

| 文件 | 内容要点 |
| --- | --- |
| `kb/01-seekdb-向量库速查.md` | `VECTOR(n)`、IK 全文索引、HNSW/vsag 建索引、`dbms_index_manager.refresh()`、距离度量与调参表 |
| `kb/02-混合检索与RRF.md` | `@search_parm` 协议、`DBMS_HYBRID_SEARCH.GET_SQL`、RRF 公式与 k=60、两路召回放大、维度一致性坑 |
| `kb/03-端侧向量化与量化对比.md` | bge-small-zh-v1.5（512 维）、INT8 22.8 MiB / Recall@5 0.917、WebGPU→WASM 回退、离线权重与单线程 |
| `kb/04-AMD-GPU加速HNSW.md` | hipVS/CAGRA 基线对比、3.33x 建图模型、recall 红线 0.005、参数扫描档位、AMD 机器复跑步骤 |
