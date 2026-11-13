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
  run.py                    # 零依赖入口：默认跑主流程自检（SELFCHECK PASS，退出码 0）
  verify.py                 # 四项验收：规则引擎 / 自检 / /health / POST /api/review
  EVIDENCE_ROOT.json        # 真·seekdb 内核跑出来的证据（DDL / 写入 / 检索计划 / 命中片段）
  seekdb_service/           # 真·seekdb 存取层 + 规则知识库 + 审查接入层 + 证据生成脚本
  rules/sql_review_rules.md # 规则说明，编号与实现一一对应
  tests/test_rules.py       # 22 个规则用例
  tests/test_app_smoke.py   # 1 个 Streamlit AppTest 冒烟用例
  PROMPT.md                 # 在 Qoder 里用的提示词、生成物对照表、Qoder Sites 发布步骤
  README.md                 # 完整交付说明
  requirements.txt / .env.example   # requirements.txt 只有注释：主流程零第三方依赖
```

## 评测怎么跑（评委侧，1 分钟）

```bash
python run.py            # 主功能自检：打印 SELFCHECK PASS，退出码 0，零第三方依赖
python run.py --serve    # 想交互体验：-> http://127.0.0.1:8501（/health、POST /api/review）
```

## seekdb 实际怎么参与审查（可复现）

规则知识存在**真实 seekdb 内核**的 `qoder_rule_knowledge` 表（`VECTOR(512)` + IK 全文索引
+ HNSW 向量索引），审查时由内核生成混合检索计划（全文分支 + 向量分支，RRF 在内核内融合），
取回的依据作为每条问题的 `basis` 返回；每轮审查写回 `qoder_review_log`。

```bash
pip install -r requirements-seekdb.txt      # pylibseekdb + 向量依赖
python seekdb_service/fetch_model.py        # bge-small-zh INT8 权重（约 23 MiB）
python run.py                               # 追加输出：[seekdb] PASS 规则知识 15 条入库；混合检索命中 N 条；审查历史 M 行写入
python seekdb_service/capture_evidence.py   # 重新生成 EVIDENCE_ROOT.json（真内核证据）
```

没装 `pylibseekdb` 也能跑：`run.py` 依旧 `SELFCHECK PASS`（输出 `[seekdb] SKIP`），
`/api/review` 里会写明降级原因 —— 判定依据与主功能不依赖内核是否到位。

以下为可选的完整 Streamlit 界面（需要联网装 streamlit，非主流程）：

```bash
pip install -r requirements-ui.txt
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
