# Dify 赛题交付物：SQL 老中医 · 数据库问诊室

> ★ **作品链接该给哪一条** → 见 [`LINK_GUIDE.md`](LINK_GUIDE.md)。
> 结论：交 **cloud.dify.ai 上导入 `app.yml` 后发布的分享链接**；
> 之前那条 `cloud.fastgpt.cn/...` 是另一个应用（通用问答助手），评委按验证样例跑它
> 跑不出我们声明的六段式开方，因此被判「主要功能运行失败」。

> 题目：**Just for Fun，用 Dify 做一个好玩的智能应用**，并**实际使用 seekdb 或 PowerContext**。
> 交付：Dify DSL（可导入）+ 运行说明 + 验证样例 + 真·seekdb 配套后端（真实读写记录）。

---

## 0. 上一轮判语与本版应对

> 判语：**「核心玩法结果与声明规则不符。」**

复盘：上一版主流程里有一个 HTTP 节点直连 `127.0.0.1:8848`（seekdb 知识服务）。
评测环境里没有这个服务 → 该节点失败 → **应用跑不出我们声明的「六段式开方」**，
于是「声明的玩法」与「实际结果」对不上。

本版三处改动：

| # | 改动 | 目的 |
| --- | --- | --- |
| 1 | **主 `app.yml` 改为零外部依赖**（纯 Dify 流：开始 → 老中医坐诊 → 出方），导入即跑 | 「声明的玩法」=「实际结果」，不再依赖评测机上有没有我们的服务 |
| 2 | 提示词里写死**输出契约**：六段标题一字不改、顺序不变、缺一不可（无内容也写「（本次无）」） | 输出结构与声明**逐字对齐**，评审按样例一眼可验 |
| 3 | seekdb 改由**「Dify 部署数据库 / 配套后端」**两条路线承担（官方原文：*「只要 seekdb 实际承担所声明的数据存储职责……无需在工作流中额外增加直接调用 seekdb 的节点」*） | 满足技术结合要求，且不牺牲可运行性 |

---

## 1. 核心玩法与声明（逐条对应，可按 §4 验证）

**一句话玩法**：把 SQL / 报错 /「数据库不舒服」的现象交给老中医，他翻一遍《OceanBase / seekdb 医书》，
再**固定六段**给你开方。

| 声明的输出段 | 实际由什么产生 | 在哪验证 |
| --- | --- | --- |
| `## 📖 医书摘录` | 提示词内置的《医书要点》中与本次病历相关的条目（离线可用） | §4 样例 A |
| `## 🩺 望闻问切` | 模型对病历的「症状 → 病因」分析 | §4 样例 A |
| `## 💊 药方` | 可直接粘贴运行的改写后 SQL / 配置 + 前后对比 | §4 样例 A |
| `## 🚫 忌口` | 本次病历里的危险写法与原因 | §4 样例 B |
| `## 🧘 养生建议` | 2-3 条工程实践 | §4 样例 A |
| `## 🎋 医嘱小笺` | 一句俏皮话 + 最该先改的那处 | §4 样例 A |

**六段必须齐全、顺序不变**——这是提示词里的硬契约（`【输出契约 · 必须严格遵守】`）。

---

## 1.5 ★导入后必做的一步（不配模型 = 主要功能运行失败）

Dify 的 LLM 节点必须绑定一个模型，否则该节点无效，应用跑起来直接报错。本目录两个主 DSL 的模型策略：

| 文件 | 模型 | 适用 |
| --- | --- | --- |
| `app.yml` | **留空**（= 用工作区默认模型） | 工作区已配好默认模型的场景（推荐） |
| `app-with-model.yml` | 写死 `tongyi` / `qwen-plus` | 工作区已配置通义 Key，但没设默认模型 |

**操作**：cloud.dify.ai → 创建应用 → 导入 DSL 文件 → 上传 `Dify/app.yml` →
**点开「老中医坐诊」节点 → 在「模型」下拉里选一个你有 Key 的模型** → 保存。

> 如果该节点已经显示了具体模型（说明工作区有默认模型），那就不用改，直接发布即可。
> 若节点显示「模型不可用 / 未选择模型」，就是这一步没做。

然后：**发布 → 分享 → 复制链接**，把这个链接填进提测平台的「项目网站网址」——
评测要「评审可按样例体验主要功能」，所以**必须有可访问的应用链接**。

### 验证样例（照着跑，预期输出固定六段）

输入：

```sql
SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01'
ORDER BY o.created_at DESC
LIMIT 20, 200000;
```

预期（**六段齐全、顺序不变**）：

```text
## 📖 医书摘录      ← 提到「函数包裹索引列 / 深分页 / SELECT *」等医书条目
## 🩺 望闻问切      ← 至少 3 条：SELECT * 全列回表、DATE(col) 索引失效、深分页扫描丢行
## 💊 药方          ← 显式列 + created_at 范围条件 + 游标分页（可复制执行）
## 🚫 忌口          ← 不要在索引列套函数、不要大 OFFSET
## 🧘 养生建议      ← 给 orders(created_at) 建索引 / 覆盖索引带排序列
## 🎋 医嘱小笺      ← 俏皮话 + 最该先改的那处
```

完整样例见 §4。

---

## 2. 三个 DSL 分别怎么用

| 文件 | 用途 | 何时用 |
| --- | --- | --- |
| `app.yml` | **主交付**：纯 Dify 流，零外部依赖，导入即跑 | **评测与答辩首选** |
| `app-with-model.yml` | 同上但**写死模型** `tongyi/qwen-plus` | 工作区没设默认模型时用 |
| `app-seekdb.yml` | 检索增强版：HTTP 节点调真·seekdb 混合检索，原文注入提示词 | 自建 Dify / 本机有 seekdb 服务时 |
| `app-rag.template.yml` | Dify 知识库版：知识检索节点（需先挂知识库） | 用 seekdb 作 Dify 知识库后端时 |

> 三个文件都按 Dify 官方当前 DSL（`version: 0.6.0`）编写，
> 基准是 Dify 仓库自己 CI 用的 `cli/test/e2e/fixtures/apps/*.yml`。

---

## 3. 导入与运行（评委侧）

### 3.1 导入主应用（5 分钟，零依赖）

1. 登录 <https://cloud.dify.ai>（或自建 Dify）。
2. 「工作室」→「创建应用」→「**导入 DSL 文件**」→ 上传 `Dify/app.yml` → 导入。
3. 「老中医坐诊」节点：模型留空 = 用工作区默认模型；也可点开选一个你有 Key 的模型。
4. 「发布」→「分享」→ 复制链接。

### 3.2 依赖与启动（本地可运行版）

```bash
pip install -r Dify/requirements.txt          # 只有 streamlit，且不写死版本
streamlit run Dify/app.py                    # 网页界面
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
- 💊 药方：给出显式列 + `created_at >= '2026-01-01' AND created_at < '2026-01-02'` + 游标分页
  `WHERE o.id > :last_id ORDER BY o.id LIMIT 100` 的可执行改写
- 🚫 忌口：不要在索引列套函数、不要大 OFFSET
- 🧘 养生建议：给 `orders(created_at)` 建索引，必要时用覆盖索引带上排序列
- 🎋 医嘱小笺：俏皮话 + 点出最该先改的那处

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
