# 在 Qoder 中使用的提示词与发布说明

## 1. 原始提示词（提交给 Qoder 的第一句话）

```text
请帮我用 Python 写一个 Streamlit 应用，调用大模型 API 做一个「数据库代码审查助手」。
```

## 2. 追加迭代提示词（把需求说清楚）

```text
补充要求：
1. 侧边栏放模型配置（Base URL / 模型名 / API Key），主区域放 SQL 输入框和「开始审查」按钮；
2. 审查结果按 阻断 / 警告 / 提示 三级展示，每条给出问题、修复建议和命中的 SQL 片段；
3. 规则要覆盖：UPDATE/DELETE 缺 WHERE、JOIN 缺 ON、SELECT *、LIKE '%x'、深分页 OFFSET、
   索引列被函数包裹、NOT IN 与 NULL、建表缺主键；
4. 模型走 OpenAI 兼容协议，方便在魔搭 / StepFun / MiniMax 之间切换；
5. 支持把审查结果导出成 Markdown 报告。
```

## 3. Qoder 生成物 → 本仓库增强点

| 环节 | Qoder 生成 | 本仓库补齐 |
| --- | --- | --- |
| 界面 | Streamlit 布局、侧边栏、按钮 | 增补示例 SQL 切换、三级颜色、报告/JSON 双导出 |
| 审查逻辑 | 调用大模型出结论 | 增加 `reviewer.py` 15 条**确定性静态规则**，离线可用、可进 CI |
| 模型接入 | 单一 provider | `PROVIDER_PRESETS` 统一魔搭 / StepFun / MiniMax / OpenAI 四套预置 |
| 健壮性 | 直接 `openai` 依赖 | 仅用标准库 `urllib` 发请求，异常不崩 UI |
| 规则文档 | — | `rules/sql_review_rules.md` 规则编号与实现一一对应 |
| 测试 | — | `tests/test_rules.py` 覆盖每条规则的触发与不触发样例 |

## 4. Qoder Sites 发布（拿项目链接）

1. 在 Qoder 中打开本项目目录（`Qoder/`），确认 `app.py` 可运行。
2. Qoder 右侧「Sites / 发布」→ 选择 Streamlit 模板 → 填入启动命令：

   ```bash
   pip install -r requirements.txt && streamlit run app.py --server.port $PORT
   ```

3. 在 Qoder Sites 的环境变量里填 `MODELSCOPE_API_KEY`（或你已配好的 StepFun / MiniMax Key）。
4. 点发布，拿到形如 `https://<xxx>.qoder.site` 的公网链接。

> 评测要求「截个图，证明是你用 Qoder 生成的」——请在 Qoder 对话界面
> （能看到上面的提示词与生成的 diff）截图，保存到 `Qoder/screenshots/`。

## 5. 截图清单

| 文件名 | 内容 |
| --- | --- |
| `01-qoder-chat.png` | Qoder 对话界面 + 提示词 + 生成的代码 diff |
| `02-qoder-files.png` | Qoder 工程文件树（app.py / reviewer.py / rules/） |
| `03-qoder-sites.png` | Qoder Sites 发布成功 + 公网链接 |
| `04-app-running.png` | 应用运行界面 + 审查结果 |
