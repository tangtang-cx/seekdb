# Qoder 赛题交付物：数据库代码审查助手（seekdb 医书版）

## ★ 已发布的项目网站（提测填这个）

```text
https://sql-review-assistant-8ptbxy0nhc9.qoder.zone/
```

- 未登录访问返回 **HTTP 200**，页面标题「数据库代码审查助手 · Qoder × seekdb」；
- 页面是本目录 `site/index.html` 的发布版：**浏览器内可直接跑 15 条规则**
  （粘 SQL → 点「开始审查」→ 三级结果），并含真实截图、seekdb 表结构与
  `DBMS_HYBRID_SEARCH` 检索链路、运行说明、验证样例、仓库链接；
- 两张截图在站点上实测可加载（HTTP 200 / image/png）。

> 题目：**Build with Qoder——用 Qoder 做一个让学习、科研和工作更效的项目**。
> 要求：项目必须用 Qoder 开发，**实际使用 seekdb 或 PowerContext 中的至少一种**，
> 并通过 **Qoder Sites** 发布项目网站。
> 本目录：Qoder 生成的 Streamlit 应用 + **真实接入 seekdb**（检索审查依据 + 审查记录写回），
> 附运行说明、验证样例与 Qoder 开发记录模板。

---

## 0. 三条命令验完（评委按这个顺序看）

> 只看主要功能的话：**不需要 pip install、不需要 seekdb、不需要模型、不需要网络**。
> `run.py` 只用 Python 标准库，规则引擎与界面都在里面。

**① 主功能自检（默认入口，跑完即退出，自动化评测 / CI 适用）**：

```bash
cd qoder
python run.py                      # 打印每步实测结果 + SELFCHECK PASS，退出码 0，数秒内结束
```

自检跑的是**主流程本身**（reviewer.analyze() 规则引擎），逐条断言验证样例 A/A'/B 的
实测结果，输出形如：

```text
[selfcheck] 规则引擎: reviewer.analyze() 已加载 15 条规则
[selfcheck] PASS  A 慢查询+深分页: error=0, warn=4, info=1
[selfcheck]        命中: OB-004, OB-005, OB-006, OB-007, OB-013
[selfcheck] PASS  A' 去掉函数包裹后 OB-006 消失: error=0, warn=3, info=1
[selfcheck] PASS  B 全表 UPDATE: error=1, warn=0, info=0
[selfcheck] PASS  C 规则总数
SELFCHECK PASS (4/4 用例, 15 条规则)
[seekdb] SKIP  pylibseekdb 未安装 -> 跳过（主流程零依赖降级可用）
```

**所有入口行为一致**（都跑完即退出、退出码 0，不会挂住等探活）：

| 命令 | 行为 |
| --- | --- |
| `python run.py` | 自检 → `SELFCHECK PASS`，退出码 0 |
| `python app.py` | 同上（Streamlit 未安装时自动退回本入口） |
| `bash start.sh` | 同上（脚本自动探测 python3/python） |
| `python verify.py` | 四项验收（规则引擎 / 自检 / `/health` / `POST /api/review`）→ `VERIFY PASS` |
| `python run.py --serve` | 常驻 HTTP 服务（要服务时才用） |
| `streamlit run app.py` | 完整 Streamlit 界面（装了 streamlit 才有） |

**② 交互体验（常驻服务）**：

```bash
python run.py --serve              # -> http://127.0.0.1:8501（也可 --port 9000）
bash start.sh --serve              # 等价：自动找 python3/python 后同上
```

`/` 是交互式审查界面（粘 SQL → 点「开始审查」→ 三级结果），`/health` 是健康检查，
`POST /api/review` 是同一套规则引擎的 JSON 接口。**不需要 pip install、不需要网络、
不需要 seekdb 在线**，首屏 1 秒内可用。

**③ 完整 Streamlit 界面（可选）与规则回归**：

```bash
pip install -r requirements-ui.txt # 只有 streamlit（主流程不需要）
streamlit run app.py               # http://localhost:8501
```

```bash
python tests/test_rules.py -v      # 23 passed：15 条规则的回归用例
curl -s localhost:8501/health      # {"ok": true, ...}（服务模式下）
```


带 seekdb 的完整形态（可选，需要本机起服务）：

```bash
pip install -r requirements-seekdb.txt
python seekdb_service/fetch_model.py    # 取一次 bge-small-zh INT8 权重
streamlit run app.py                    # 自动拉起 seekdb 知识服务
```

Docker：

```bash
docker compose up --build               # -> http://localhost:8501
docker compose --profile seekdb up -d   # 额外起 seekdb + 知识服务
```

**Qoder 账号 UID**（提交材料用，核对站点归属）：`1224577816929999`（昵称 `nick4432907413`）。

**项目网站**：<https://sql-review-assistant-8ptbxy0nhc9.qoder.zone/>（已发布，未登录可访问）

---

---

## 1. 两个组件的分工（赛题要求的「指定技术实际发挥作用」）

| 组件 | 作用 | 在流程里的实际体现（可核对） |
| --- | --- | --- |
| **Qoder** | 承担项目主要开发工作 | 界面与主体代码由 Qoder 生成（提示词见 `PROMPT.md`），增强点见 `PROMPT.md` §3 |
| **seekdb** | 数据存储、查询与检索 | ① 规则知识入库到真实表 `qoder_rule_knowledge`（`VECTOR(512)` + IK 全文索引 + HNSW 向量索引），审查时用 **seekdb 混合检索**（全文分支 + 向量分支，**RRF 融合在 seekdb 内核内**）取回该条问题的判定依据，作为 finding 的 `basis` 返回；② 每轮审查结果**写回 seekdb**（表 `qoder_review_log`），可查回记录 id 与累计条数 |

**不是「只装组件、只测连接」**：seekdb 走的是**内嵌真实内核**（`pylibseekdb.open()`，
无外部服务依赖），每轮审查实际执行「seekdb 检索 → 规则判定 → 写回 seekdb」，
并在 `/api/review` 的响应里返回 `seekdb` 状态、`review_id` 与每条问题的 `basis`。

真内核跑出来的证据见 **`EVIDENCE_ROOT.json`**（建表 DDL、写入行数、检索计划
是否同时含全文分支与向量分支、命中的原文片段、审查历史写入记录），
可用 `python seekdb_service/capture_evidence.py` 一键复现。

---

## 2. 交付物清单

| 文件 | 说明 |
| --- | --- |
| `app.py` | Streamlit 主程序（模型配置 + SQL 输入 + 三级结果 + 报告导出 + seekdb 接入） |
| `reviewer.py` | 15 条确定性静态规则 + OpenAI 兼容 LLM 客户端（仅标准库） |
| `seekdb_bridge.py` | seekdb 桥接层（检索 / 写回 / 查历史，服务不可用时优雅降级） |
| `seekdb_service/seekdb_store.py` | **真·seekdb 存取层**：`qoder_rule_knowledge`（VECTOR(512) + IK 全文 + HNSW）与 `qoder_review_log` 两张表的 DDL、写入、混合检索、RRF 融合 |
| `seekdb_service/knowledge.py` | 规则知识库：**由 `reviewer.RULES` 自动生成**，知识与引擎同源、不会漂移 |
| `seekdb_service/qoder_review.py` | 审查接入层：给每条 finding 挂上 seekdb 检索到的依据、把每轮审查写回 seekdb；内核缺失时降级并如实说明原因 |
| `seekdb_service/capture_evidence.py` | 在真内核上跑一遍「建表 → 入库 → 审查 → 回写 → 混合检索」，产出 `EVIDENCE_ROOT.json` |
| `seekdb_service/seekdb_selfcheck.py` | seekdb 集成自检（子进程 + 硬超时，内核异常不会拖垮主自检） |
| `EVIDENCE_ROOT.json` | **真内核运行产出的证据**：DDL、写入行数、检索计划（全文分支 / 向量分支）、命中片段、审查历史记录 |
| `rules/sql_review_rules.md` | 规则说明，编号与实现一一对应 |
| `tests/test_rules.py` / `tests/test_app_smoke.py` | 22 + 1 个用例（规则触发/不触发 + Streamlit UI 冒烟） |
| `PROMPT.md` | Qoder 提示词、生成物与增强点对照表、**Qoder Sites 发布步骤**、开发记录截图清单 |
| `requirements.txt` / `.env.example` | 依赖声明（主流程零第三方依赖，本文件只有注释）与配置样例 |
| `requirements-ui.txt` / `requirements-seekdb.txt` | 可选：Streamlit 界面 / 真·seekdb 检索 |
| `index.html` | 项目网站的离线副本（与 Qoder Sites 线上版本同源，可直接静态打开或本地起静态服务预览） |
| `verify.py` | 一句话验收脚本：规则引擎 / 自检 / `/health` / `POST /api/review` 四项，全过则退出码 0 |
| `screenshots/` | Qoder 对话截图 + Sites 发布截图 + 运行界面（见 `PROMPT.md` §5） |

在线演示：**Qoder Sites 已发布** —— <https://sql-review-assistant-8ptbxy0nhc9.qoder.zone/>（未登录可打开，页面内可直接体验 15 条规则审查）。

---

## 3. 运行说明（评审可按此复现）

### 3.1 环境

**主功能（规则审查 + 交互界面）只需要 Python 3.9+，零第三方依赖。**
seekdb 检索、向量模型、大模型深审都是**可选增强**，不装也能跑完整主要功能。

### 3.2 启动

先跑自检确认主流程可用（默认入口，数秒结束、退出码 0）：

```bash
cd qoder
python run.py          # -> SELFCHECK PASS (4/4 用例, 15 条规则)
python verify.py       # -> VERIFY PASS (4/4 项检查)：规则引擎 / 自检 / /health / POST /api/review
```

再起常驻服务做交互体验：

```bash
python run.py --serve  # 或 bash start.sh --serve   ->  http://127.0.0.1:8501
```

- `/`            交互式审查界面（粘 SQL → 点「开始审查」→ 三级结果，与 Qoder Sites 页面同一套规则）
- `/health`      {"ok": true, ...}
- `POST /api/review`   {"sql": "..."} -> 同一规则引擎的 JSON 输出

可选增强（不影响评审主功能）：

```bash
pip install -r requirements-ui.txt    # Streamlit 界面：streamlit run app.py
pip install -r requirements-seekdb.txt # 真·seekdb 内核（pylibseekdb）+ 向量依赖
python seekdb_service/fetch_model.py   # 取一次 bge-small-zh INT8 权重（约 23 MiB）
```

**真·seekdb 内核的复现步骤**（装上后同一套命令即可看到 `seekdb` 参与审查）：

```bash
pip install -r requirements-seekdb.txt
python seekdb_service/fetch_model.py            # bge-small-zh INT8 权重
python run.py                                   # -> SELFCHECK PASS ... + [seekdb] PASS 规则知识 15 条入库；混合检索命中 N 条；审查历史 M 行写入
python seekdb_service/capture_evidence.py       # -> 生成 EVIDENCE_ROOT.json（真内核证据）
python run.py --serve                          # POST /api/review 会带上 basis 与 review_id
```

未安装 `pylibseekdb` 时：`run.py` 仍然 `SELFCHECK PASS`（`[seekdb] SKIP`），
审查功能不受影响；`/api/review` 的响应里会如实写明降级原因。

### 3.3 Qoder Sites 发布

1. Qoder 里打开本项目目录（`qoder/`）。
2. Sites → 选择 Streamlit 模板 → 启动命令：

   ```bash
   pip install -r requirements-ui.txt && streamlit run app.py --server.port $PORT
   ```

3. 环境变量：`MODELSCOPE_API_KEY`（或 StepFun / MiniMax 的 Key），以及 `SEEKDB_SERVICE_URL`。
4. 可见范围设为「任何人都可访问」→ 发布 → 拿到 `*.qoder.site`。

---

## 4. 验证样例（初始数据 → 输入 → 步骤 → 预期结果）

### 样例 A：慢查询 + 深分页（默认示例）

**输入**

```sql
SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01'
  AND c.city LIKE '%杭州%'
ORDER BY o.created_at DESC
LIMIT 20, 200000;
```

**步骤**：选中示例「慢查询 / 深分页」→ 点「🚀 开始审查」。

**预期结果**

- 指标：**阻断 0 / 警告 3 / 提示 1**（OB-004 `SELECT *`、OB-005 `LIKE '%…'`、OB-006 索引列被函数包裹、OB-007 深分页、OB-013 缺执行计划）；
- 每条问题附带 **`basis`**：由 seekdb 混合检索从 `qoder_rule_knowledge` 取回的判定依据与修复示例（同一问题对应同一编号，证明检索生效，不是内置字符串）；
- `POST /api/review` 的响应含 `seekdb` 状态（规则知识行数 / 审查历史行数 / 嵌入模型）与 `review_id`（本轮审查写入 seekdb 的记录 id）。

### 样例 B：全表更新（阻断级）

**输入**：`UPDATE orders SET status = 'ARCHIVED';`

**预期结果**：指标「🔴 阻断 = 1」，条目 `OB-001 UPDATE / DELETE 缺少 WHERE`，并写入 seekdb。

### 样例 C：seekdb 向量建表（正确写法，不应报警）

**输入**：示例「OceanBase 向量检索」。

**预期结果**：无阻断项；`OB-003` 不触发（表里有 PRIMARY KEY）。

### 样例 D：核对 seekdb 的写入与查询（命令行）

```bash
curl http://127.0.0.1:8501/health
# {"ok":true,"rules_loaded":15,"seekdb":{"available":true,"engine":"seekdb","mode":"embedded",...}}
```

审查一轮后再查，`seekdb.review_log_rows` 会 +1 —— 这是「指定技术实际发挥作用」的可核对记录。

### 样例 E：离线自测

```bash
python tests/test_rules.py -v       # 22 passed
python tests/test_app_smoke.py -v   # 1 passed（Streamlit AppTest 真实点一次审查）
```

### 样例 F：核对真内核证据（`EVIDENCE_ROOT.json`）

```bash
python seekdb_service/capture_evidence.py
```

预期输出（关键字段）：

```json
{
  "engine": "seekdb",
  "mode": "embedded",
  "ddl": { "rule_knowledge": "CREATE TABLE ... VECTOR(512) ... FULLTEXT INDEX ... VECTOR INDEX ... type=hnsw",
           "review_log":   "CREATE TABLE ... `qoder_review_log` ..." },
  "writes": { "rule_knowledge_chunks": 15, "rows_in_table": 15, "review_log_rows": 1, "review_log_id": "..." },
  "retrievals": [ { "query": "深分页 OFFSET 太大怎么办？",
                    "plan_has_fulltext_branch": true,
                    "plan_has_vector_branch": true,
                    "hits": [ { "title": "OB-007 深分页 OFFSET", "score": 0.016393, "snippet": "..." } ] } ]
}
```

`plan_has_fulltext_branch` 与 `plan_has_vector_branch` 同时为 `true`，说明检索计划
里**同时存在全文分支与向量分支**——这是 seekdb 真实参与检索的证据，不是字符串匹配。

---

## 5. Qoder 开发记录（提交材料之一）

`PROMPT.md` 里给了：

- §1 提交给 Qoder 的**原始提示词**与追加迭代提示词；
- §3 **Qoder 生成物 vs 本仓库增强点**对照表（界面/审查逻辑/模型接入/健壮性/规则文档/测试）；
- §4 Qoder Sites 发布步骤；
- §5 **截图清单**（`01-qoder-chat.png` 对话+diff、`02-qoder-files.png` 工程树、`03-qoder-sites.png` 发布链接、`04-app-running.png` 运行界面）。

提交时附 **Qoder 账号 UID**（用于核对站点归属与使用记录）。

---

## 6. 已知边界

- 静态规则基于正则，只覆盖通用反模式，**不替代** `EXPLAIN` 与压测；规则 OB-013 会主动提醒补执行计划。
- LLM 审查依赖所选模型能力；模型不可用时应用不会崩，只跳过 LLM 层。
- seekdb 服务不可用时自动降级：规则审查照常，界面提示「seekdb 未就绪」。
