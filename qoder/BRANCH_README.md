# Qoder 赛题提交分支

题目：**Qoder · 数据库代码审查助手**

提测时填写：

| 项 | 值 |
| --- | --- |
| 仓库 | `https://github.com/tangtang-cx/seekdb` |
| 分支 | `qoder` |
| Commit SHA | 取该分支最新 commit 的完整 40 位 SHA（见 <https://github.com/tangtang-cx/seekdb/commits/qoder>） |

## 项目网站（已发布，公开可访问）

```text
https://sql-review-assistant-8ptbxy0nhc9.qoder.zone/
```

未登录 HTTP 200；页面内含浏览器端 15 条规则交互演示、真实截图、seekdb 表结构与
`DBMS_HYBRID_SEARCH` 检索链路、运行说明、验证样例与仓库链接。

## 提交物

```text
Qoder/
  app.py                    # Streamlit 主程序（模型配置 + SQL 输入 + 三级结果 + 报告导出）
  reviewer.py               # 15 条确定性静态规则 + OpenAI 兼容 LLM 客户端（仅标准库）
  rules/sql_review_rules.md # 规则说明，编号与实现一一对应
  tests/test_rules.py       # 22 个规则用例
  tests/test_app_smoke.py   # 1 个 Streamlit AppTest 冒烟用例
  PROMPT.md                 # 在 Qoder 里用的提示词、生成物对照表、Qoder Sites 发布步骤
  README.md                 # 完整交付说明
  requirements.txt / .env.example
```

## 评测怎么跑（评委侧，1 分钟）

```bash
pip install -r requirements.txt
export MODELSCOPE_API_KEY=ms-xxxxxxxx      # 或 STEPFUN_API_KEY / MINIMAX_API_KEY
streamlit run app.py
```

打开 <http://localhost:8501>，粘贴 SQL → 点「🚀 开始审查」→ 得到
🔴阻断 / 🟠警告 / 🔵提示 三级结果与可下载的 Markdown / JSON 报告。

**离线也能用**：不填 API Key 时静态规则引擎照常工作（15 条规则、毫秒级）。

## 自测

```bash
python Qoder/tests/test_rules.py -v       # 22 passed
python Qoder/tests/test_app_smoke.py -v   # 1 passed
```

## 说明

应用界面与主体代码由 **Qoder AI IDE** 按 `PROMPT.md` 里的提示词生成，
本仓库在其基础上补齐了确定性规则引擎、多 provider 预置与测试。
发布到 Qoder Sites 的公网链接与截图位置见 `PROMPT.md` §4、§5。

详细文档见 [`Qoder/README.md`](Qoder/README.md)。
