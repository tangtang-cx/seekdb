# Dify 题 · 作品链接怎么给（重要）

## 结论

| 链接 | 能不能当 Dify 题的作品链接 |
| --- | --- |
| `https://cloud.fastgpt.cn/chat/share?shareId=cbW1j7q9td1AOUZZcakQbgiZ` | ❌ **不能**。这是 FastGPT 上的另一个应用（通用「我的问答助手」），不是我们的 Dify 应用。评委按验证样例跑它，跑不出我们声明的六段式开方 → 判「主要功能运行失败」 |
| `https://cloud.dify.ai/chat/share?shareId=...`（导入 `dify/app.yml` 后发布） | ✅ **这才是要交的** |

---

## 路线 1（正解，约 6 分钟）：在 Dify 官方云发布

1. 登录 <https://cloud.dify.ai>。
2. 「工作室」→「创建应用」→「**导入 DSL 文件**」→ 上传 `dify/app.yml` → 导入。
3. **点开「老中医坐诊」节点 → 选一个模型**（不选则该节点无效 → 运行失败）。
   - 工作区没配默认模型 → 改用 `dify/app-with-model.yml`（已写死 `tongyi/qwen-plus`）。
4. 「发布」→「分享」→ 复制链接。
5. 提测平台「项目网站网址」填这条链接。

导入后按 §2 的样例验一遍，输出必须是六段：

```text
## 📖 医书摘录 / ## 🩺 望闻问切 / ## 💊 药方 / ## 🚫 忌口 / ## 🧘 养生建议 / ## 🎋 医嘱小笺
```

---

## 路线 2（兜底，10 分钟内）：把现有 FastGPT 应用改造成"符合声明"

如果时间紧、来不及在 Dify 官方云发布，可以先把**现有那个 FastGPT 应用**改成我们的玩法，
让同一条链接的**实际表现 = 声明**，再交上去（至少不会再被判"运行失败"）。
但注意：题面写明「必须使用 Dify」，交 FastGPT 链接仍有被判不符的风险。

### 2.1 把医书灌进它的知识库

它的知识库 id 是 `PvxGnL0sbXZQu1owx1QAX65S`（就是 `Dify/README.md` §5 里那个）。

```bash
export FASTGPT_API_KEY=fastgpt-xxxxxxxx      # FastGPT -> 个人设置 -> API 密钥
python Dify/scripts/push_docs_to_fastgpt.py --dataset-id PvxGnL0sbXZQu1owx1QAX65S
```

脚本会把 `Dify/kb/` 的 4 篇文档上传进去（真实 seekdb 实测结论），并回显文档列表。

### 2.2 把系统提示词换成我们的六段式契约

在 FastGPT 应用编辑页 → 「提示词 / Prompt」→ 粘贴下面这段（与 `dify/app.yml` 里的提示词同源）：

```text
你是「SQL 老中医」，一位专治数据库疑难杂症的老派中医，兼 OceanBase / seekdb 资深工程师。
你手上有一本《OceanBase / seekdb 医书》（检索到的知识库片段就是医书原文）。
【输出契约 · 必须严格遵守】
每次回答必须按下面六段输出，标题一字不改、顺序不变、六段齐全，即使某段没有内容也要保留该标题并写「（本次无）」：

## 📖 医书摘录
## 🩺 望闻问切
## 💊 药方
## 🚫 忌口
## 🧘 养生建议
## 🎋 医嘱小笺

各段要求：
- 医书摘录：从知识库检索到的医书条目里挑与本次病历相关的，列出条目名与关键句；
- 望闻问切：2-4 条，每条写成「症状 → 病因」，引用病历里的具体片段；
- 药方：给出可直接粘贴运行的优化后 SQL / 配置，并给出前后对比；
- 忌口：列出本次病历里出现的危险写法与原因；
- 养生建议：2-3 条工程实践（索引设计、参数、分批、监控）；
- 医嘱小笺：一句俏皮话 + 最该先改的那一处。

只使用真实存在的语法与函数，不要编造 API：向量列写作 VECTOR(n)；HNSW 索引写作
VECTOR INDEX idx (embedding) WITH(distance=cosine, type=hnsw, lib=vsag, m=16, ef_construction=200, ef_search=64)；
全文索引用 FULLTEXT INDEX ... WITH PARSER ik；写入向量后需 CALL dbms_index_manager.refresh()。
病历信息不足时，明确列出还需要哪些信息（表结构、数据量、EXPLAIN 结果）。
```

### 2.3 把开场白也换成我们的（可选）

```text
🩺 欢迎来到「SQL 老中医 · 数据库问诊室」！把病历交给我：贴一段 SQL、甩一条报错，
或用大白话说「我的查询像老牛拉车」。我先翻一翻医书（知识库），再按固定六段给你开方：
📖 医书摘录 / 🩺 望闻问切 / 💊 药方 / 🚫 忌口 / 🧘 养生建议 / 🎋 医嘱小笺
```

### 2.4 验证（与提测样例一致）

输入：

```sql
SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01'
ORDER BY o.created_at DESC
LIMIT 20, 200000;
```

期望：六段齐全，且「📖 医书摘录」里能看到来自《OceanBase / seekdb 医书》的条目。

---

## 3. 两题对照（别再交错了）

| 赛题 | 交什么链接 |
| --- | --- |
| **Dify（600076）** | cloud.dify.ai 上导入 `dify/app.yml` 后发布的分享链接（**不是 FastGPT**） |
| **Qoder（600077）** | `https://sql-review-assistant-8ptbxy0nhc9.qoder.zone/`（Qoder Sites，已发布，实测 HTTP 200） |
| **魔搭社区** | `https://modelscope.cn/skills/wzhaihqy/oceanbase-sql-reviewer`（已提交成功） |
