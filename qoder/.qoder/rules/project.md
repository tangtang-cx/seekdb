# 项目规则（Qoder 工作区）

本目录是 Qoder 工作区规则，供 Qoder 在本项目中生成与修改代码时遵循。

## 一、运行优先零依赖

- 主入口是 `run.py`，**只允许使用 Python 标准库**；不得引入第三方包作为主流程前提。
- `python run.py` = 主流程自检（打印 `SELFCHECK PASS`，退出码 0，数秒内结束）。
- `python run.py --serve` = 常驻 HTTP 服务（`/`、`/health`、`/api/rules`、`POST /api/review`）。
- Streamlit（`app.py`）与 seekdb（`seekdb_service/`）都是**可选增强**，缺了主功能照常可用。

## 二、规则引擎单一真源

- 15 条规则的唯一定义在 `reviewer.py` 的 `RULES` 与 `analyze()`。
- 任何入口（`run.py`、`app.py`、`site/index.html` 的前端引擎）都必须与它逐条一致；
  改规则必须同步三处，并用 `python tests/test_rules.py -v` 与
  `tools/probe_site_local.mjs`（JS↔Python 逐用例比对）验证。

## 三、文档必须与实测一致

- `README.md` / `RUN.md` / `VALIDATION.md` 里的**预期输出必须是程序实际运行的输出**，
  不允许手写示意、不允许出现 `...` 省略关键结果。
- 改行为 → 先跑，再按实测结果改文档，顺序不可颠倒。

## 四、验证样例可复核

- `VALIDATION.md` 的每个样例都必须能按步骤复现：初始输入 → 操作 → 预期结果 → 实际输出。
- 样例 A/B 已固化进 `run.py` 自检；新增样例应同时加入自检断言。

## 五、提交物约定

- 项目网站：通过 Qoder Sites 发布，可见范围「任何人都可访问」。
- 代码仓库：`tangtang-cx/seekdb`，分支 `qoder`，资产放在 `qoder/` 目录。
- Qoder 账号 UID 与开发记录见 `DEVELOPMENT_LOG.md` 与 `PROMPT.md`。
- 仓库内**不得出现任何真实凭据**（API Key / 密码 / token），配置一律占位。
