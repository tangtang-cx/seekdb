# Qoder 开发记录（提交材料用）

> 官方要求：「项目的主要开发工作必须在 Qoder 中完成……参赛者需保留开发过程记录，说明 Qoder 在
> 需求拆解、编码、调试等环节中完成了哪些工作。仅用 Qoder 发布网站而项目在其他工具中开发的作品，
> 不符合本赛道要求。」
> 提交时要给的东西：**关键开发环节的 Qoder 对话截图或录屏 + Qoder 账号 UID**（核对站点归属）。

---

## 0. 需要准备的东西

| 项 | 怎么拿 | 放哪 |
| --- | --- | --- |
| Qoder 账号 UID | Qoder → **设置 → 个人资料 → 编辑** | 填进下面 §5 |
| 需求拆解截图 | Qoder 对话里让它先拆需求 | `screenshots/01-requirement.png` |
| 编码截图 | Qoder 生成 `app.py` / `reviewer.py` / `seekdb_bridge.py` 的对话 + diff | `screenshots/02-coding.png` |
| 调试截图 | Qoder 协助定位的问题（见 §2 的清单） | `screenshots/03-debugging.png` |
| 发布截图 | Sites 发布成功 + 公网链接 + 访问统计 | `screenshots/04-sites.png` |
| 使用效果 | 站点「更多 → 访问统计」（访问次数、独立访客） | `screenshots/05-usage.png` |

> 截图要**看得见 Qoder 的界面与对话内容**（能看出是 Qoder 参与完成的），
> 不要只截最终代码文件。

---

## 1. 需求拆解（让 Qoder 先拆，别直接写代码）

在 Qoder 里用这段话开场（我们提交的真实提示词）：

```text
请帮我用 Python 写一个 Streamlit 应用，调用大模型 API 做一个「数据库代码审查助手」。
```

再追加（把需求说清楚）：

```text
补充要求：
1. 侧边栏放模型配置（Base URL / 模型名 / API Key），主区域放 SQL 输入框和「开始审查」按钮；
2. 审查结果按 阻断 / 警告 / 提示 三级展示，每条给出问题、修复建议和命中的 SQL 片段；
3. 规则要覆盖：UPDATE/DELETE 缺 WHERE、JOIN 缺 ON、SELECT *、LIKE '%x'、深分页 OFFSET、
   索引列被函数包裹、NOT IN 与 NULL、建表缺主键；
4. 模型走 OpenAI 兼容协议，方便在魔搭 / StepFun / MiniMax 之间切换；
5. 支持把审查结果导出成 Markdown 报告。
```

**让 Qoder 先回一份「需求拆解 + 模块划分 + 实现顺序」**，截图这一屏 → `01-requirement.png`。

---

## 2. 编码与调试（这两段最能证明「Qoder 参与开发」）

让 Qoder 分模块写，每写完一个就让他解释/自测。推荐这个顺序，
每个环节都留一张对话截图：

| 环节 | 给 Qoder 的话 | 截图 |
| --- | --- | --- |
| 规则引擎 | 「先写 `reviewer.py`：15 条正则规则，每条返回 id / level / title / message / suggestion / snippet，标准库实现，别引入依赖」 | `02-coding.png` |
| Streamlit 界面 | 「基于 reviewer.py 写 `app.py`：侧边栏配置、主区输入、三级结果、Markdown/JSON 导出」 | `02-coding.png` |
| 接 seekdb | 「写 `seekdb_bridge.py`：调用本地 seekdb 知识服务做混合检索取依据，并把每轮审查写回 seekdb 的 `qoder_review_log` 表」 | `02-coding.png` |
| 调试：规则误报 | 「`WHERE DATE(created_at)='2026-01-01'` 应该报 OB-006 索引列被函数包裹，但规则没命中，帮我定位并修」 | `03-debugging.png` |
| 调试：依赖冲突 | 「requirements.txt 里把版本写死成 `pylibseekdb==1.4.0.post2` 会在评测机装不上，改成核心依赖只有 streamlit、增强依赖用区间」 | `03-debugging.png` |
| 调试：降级 | 「模型权重不在仓库里，onnxruntime 可能也没装，应用要能启动：embedder 缺模型时退回确定性哈希向量」 | `03-debugging.png` |
| 自测 | 「给这 15 条规则各写一个触发用例和一个不触发用例」 | `03-debugging.png` |

> §2 里那三行调试是**真实发生过的**（我们确实踩了 `DATE(col)` 漏检、依赖写死、模型缺失三个坑，
> 修复过程与结论都写在 `qoder/README.md` 与提交记录里），照着复现一遍即可，
> 截图也更有说服力。

---

## 3. 验证（跑一遍，把输出截图）

```bash
cd qoder
python tests/test_rules.py -v        # 23 passed（22 规则 + DATE 用例）
python tests/test_app_smoke.py -v    # 1 passed
python ../dify/smoke_test.py         # 项目可运行自证
```

---

## 4. 发布（Qoder Sites）

见 [`SITES_GUIDE.md`](SITES_GUIDE.md)：左侧栏「站点」→ 添加站点 → 描述需求 → 预览 →
发布 → 分享 → **任何人都可访问**（个人版要点「允许公开访问」确认）。

截图：`04-sites.png`（含发布成功状态与网站地址）、`05-usage.png`（更多 → 访问统计）。

---

## 5. 提交材料清单

| 材料 | 状态 |
| --- | --- |
| 项目网站网址（任何人可访问） | ⏳ Qoder Sites 发布后填入 |
| 代码仓库地址 | `https://wzhaihqy:<PAT>@github.com/tangtang-cx/seekdb.git` |
| 分支 / Commit | `qoder` / ⏳（提测前确认最新 40 位 SHA） |
| Qoder 账号 UID | ⏳ 设置 → 个人资料 → 编辑 |
| 运行说明 | ✅ `qoder/README.md` §2（含 Qoder Sites 启动命令与环境变量） |
| 验证样例 | ✅ `qoder/README.md` §3（4 组，含初始数据 / 输入 / 步骤 / 预期结果 / 复核命令） |
| Qoder 开发记录 | ⏳ 按 §1、§2 截图，文件名见 §0 |
| 使用效果材料（鼓励） | ⏳ 站点访问统计截图（访问次数、独立访客） |
| 技术结合证据 | ✅ seekdb 检索与写库实测记录；`qoder/README.md` §1 有表结构与分工说明 |

> 仓库里**不要**提交任何真实 API Key；`.env.example` 里全是占位值。
