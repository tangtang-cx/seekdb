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

> 题目：**Build with Qoder——用 Qoder 做一个让学习、科研和工作更效���的项目**。
> 要求：项目必须用 Qoder 开发，**实际使用 seekdb 或 PowerContext 中的至少一种**，
> 并通过 **Qoder Sites** 发布项目网站。
> 本目录：Qoder 生成的 Streamlit 应用 + **真实接入 seekdb**（检索审查依据 + 审查记录写回），
> 附运行说明、验证样例与 Qoder 开发记录模板。

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

在线演示：

```text
公网 Demo（cloudflared 隧道，地址会变）：https://clocks-remains-claire-serious.trycloudflare.com
Qoder Sites（永久链接，发布后回填）：https://________________.qoder.site
```

---

## 3. 运行说明（评审可按此复现）

### 3.1 环境

| 项 | 版本 / 要求 |
| --- | --- |
| Python | 3.10+（实测 3.13） |
| 依赖 | `pip install -r requirements.txt`（streamlit / pylibseekdb / onnxruntime / tokenizers / numpy，均为实测无冲突版本） |
| 模型文件 | `stepfun/public/models/bge-small-zh-v1.5`（tokenizer.json + onnx/model_int8.onnx，22.8 MiB）。仓库不提交大文件，用 `npm run model:fetch`（在 `stepfun/` 下）或直接下载 model repo 获取 |
| seekdb | 嵌入式（`pylibseekdb`，零外部依赖）或服务端（`oceanbase/seekdb` 容器，见 `../dify/seekdb_service/docker-compose.yml`） |
| 大模型 | 可选。魔搭 `MODELSCOPE_API_KEY` / StepFun `STEPFUN_API_KEY` / MiniMax `MINIMAX_API_KEY`，均为 OpenAI 兼容；**不填也能跑**（规则 + seekdb 检索） |

### 3.2 启动

```bash
cd qoder
pip install -r requirements.txt

# 方式 A：一键（应用会自动拉起 seekdb 服务）
streamlit run app.py

# 方式 B：先单独起服务（两个终端）
python ../dify/seekdb_service/serve.py --port 8848
streamlit run app.py
```

打开 <http://localhost:8501>。左侧应显示「seekdb 已就绪 · 模式 embedded · 知识块 19」。

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
