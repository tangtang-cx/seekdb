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
```

**② 交互体验（常驻服务）**：

```bash
python run.py --serve              # -> http://127.0.0.1:8501（也可 --port 9000）
bash start.sh                      # 等价：自动找 python 后同上
```

`/` 是交互式审查界面（粘 SQL → 点「开始审查」→ 三级结果），`/health` 是健康检查，
`POST /api/review` 是同一套规则引擎的 JSON 接口。**不需要 pip install、不需要网络、
不需要 seekdb 在线**，首屏 1 秒内可用。

**③ 完整 Streamlit 界面（可选）与规则回归**：

```bash
pip install -r requirements.txt    # 只有 streamlit
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
| **seekdb** | 数据存储、查询与检索 | ① 审查前用 **seekdb 混合检索**（本地 bge 向量 + IK 全文 + **RRF 融合在 seekdb 内核内**）取回相关「医书」条目作为审查依据，界面里可展开核对原文；② 每轮审查结果**写回 seekdb**（表 `qoder_review_log`），侧栏「🗂️ 审查历史」实时从 seekdb 查回 |

**不是「只装组件、只测连接」**：每次点「开始审查」都会真实走一遍
「seekdb 检索 → 模型（可选）作答 → 写回 seekdb」，并在界面上显示命中条数、写入的记录 id 与累计条数。

---

## 2. 交付物清单

| 文件 | 说明 |
| --- | --- |
| `app.py` | Streamlit 主程序（模型配置 + SQL 输入 + 三级结果 + 报告导出 + seekdb 接入） |
| `reviewer.py` | 15 条确定性静态规则 + OpenAI 兼容 LLM 客户端（仅标准库） |
| `seekdb_bridge.py` | seekdb 桥接层（检索 / 写回 / 查历史，服务不可用时优雅降级） |
| `rules/sql_review_rules.md` | 规则说明，编号与实现一一对应 |
| `tests/test_rules.py` / `tests/test_app_smoke.py` | 22 + 1 个用例（规则触发/不触发 + Streamlit UI 冒烟） |
| `PROMPT.md` | Qoder 提示词、生成物与增强点对照表、**Qoder Sites 发布步骤**、开发记录截图清单 |
| `requirements.txt` / `.env.example` | 依赖与配置样例 |
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
```

再起常驻服务做交互体验：

```bash
python run.py --serve  # 或 bash start.sh   ->  http://127.0.0.1:8501
```

- `/`            交互式审查界面（粘 SQL → 点「开始审查」→ 三级结果，与 Qoder Sites 页面同一套规则）
- `/health`      {"ok": true, ...}
- `POST /api/review`   {"sql": "..."} -> 同一规则引擎的 JSON 输出

可选增强（不影响评审主功能）：

```bash
pip install -r requirements.txt       # Streamlit 界面：streamlit run app.py
pip install -r requirements-seekdb.txt # 真·seekdb 检索与审查历史落库
python seekdb_service/fetch_model.py   # 取一次 bge-small-zh INT8 权重（约 23 MiB）
```

### 3.3 Qoder Sites 发布

1. Qoder 里打开本项目目录（`qoder/`）。
2. Sites → 选择 Streamlit 模板 → 启动命令：

   ```bash
   pip install -r requirements.txt && streamlit run app.py --server.port $PORT
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
- 展开「📖 seekdb 检索到的依据」：应出现来自 `01-seekdb-向量库速查.md` / `02-混合检索与RRF.md` 的**真实段落**（这证明 seekdb 检索确实生效，不是内置字符串）；
- 底部提示「本轮审查已写入 seekdb（记录 id …，累计 N 条）」。

### 样例 B：全表更新（阻断级）

**输入**：`UPDATE orders SET status = 'ARCHIVED';`

**预期结果**：指标「🔴 阻断 = 1」，条目 `OB-001 UPDATE / DELETE 缺少 WHERE`，并写入 seekdb。

### 样例 C：seekdb 向量建表（正确写法，不应报警）

**输入**：示例「OceanBase 向量检索」。

**预期结果**：无阻断项；`OB-003` 不触发（表里有 PRIMARY KEY）。

### 样例 D：核对 seekdb 的写入与查询（命令行）

```bash
curl http://127.0.0.1:8848/health
# {"ok":true,"mode":"embedded","chunks":19,"reviews":3,...}
```

`reviews` 随每次审查递增 —— 这是「指定技术实际发挥作用」的可核对记录。

### 样例 E：离线自测

```bash
python tests/test_rules.py -v       # 22 passed
python tests/test_app_smoke.py -v   # 1 passed（Streamlit AppTest 真实点一次审查）
```

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
