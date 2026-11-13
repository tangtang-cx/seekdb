# 路线 A：把 seekdb 作为 Dify 的部署数据库

> **本文档描述的是可选增强，不是评测对象。**
> 主交付是 `app.yml`（workflow：开始 → 规则体检 code 节点 → 出方），
> **不需要 seekdb、不需要模型、不需要外部服务**。下面这套 seekdb 检索增强
> 只在你想看「真·向量检索」时使用，评测时可以完全忽略。

> 官方原文：*「支持使用 seekdb 作为自行部署 Dify 时使用的数据库。参赛者应明确 seekdb 承载的是
> 知识库向量存储、应用数据存储或其他数据，并提供支持相应用途的 Dify 版本或适配分支、seekdb 版本及
> 部署配置。只要 seekdb 实际承担所声明的数据存储职责，且应用的主要功能可按说明正常体验，即满足
> seekdb 的使用要求，无需在工作流中额外增加直接调用 seekdb 的节点。」*

本文件说明：**seekdb 承载什么**、**版本与分支**、**部署配置**、**初始化**、**实际读写验证步骤**。

---

## 1. seekdb 承载的职责（声明）

| 职责 | 承载内容 | 落在哪张表 |
| --- | --- | --- |
| **Dify 的业务数据库** | Dify 自身的工作区、应用、对话、凭据等元数据 | Dify 默认库（MySQL 协议，seekdb 兼容） |
| **知识库向量存储** | 本作品《OceanBase / seekdb 医书》的向量 + 全文索引 | `dify_knowledge_base`（`VECTOR(512)` + `FULLTEXT ... PARSER ik` + `VECTOR INDEX ... type=hnsw, lib=vsag`） |
| **应用数据存储** | 审查/问诊历史、用户反馈记录 | `qoder_review_log`（Dify 路线下由配套服务写入同库） |

---

## 2. 版本与分支

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| seekdb | `oceanbase/seekdb:latest`（本项目实测 `pylibseekdb 1.4.0.post2`，内核 1.4） | MySQL 协议兼容，可直接被 Dify 当作 DB 使用 |
| Dify | 官方 `langgenius/dify` 的 `docker` 部署（1.x，官方镜像 `langgenius/dify-api:1.x`） | **无需改代码**：Dify 只通过 MySQL 协议访问数据库，seekdb 兼容该协议 |
| 适配点（若需要） | 把 Dify 的 `docker/.env` 里 `DB_*` 指向 seekdb；若 Dify 版本使用 MySQL 8 专属 DDL 报错，用我们已验证的表结构建库后再导入 | 见 §3 |

> 若官方 Dify 版本对 seekdb 的 DDL 有个别不兼容项，适配只需改 **建表 SQL**，
> 不涉及应用逻辑；本仓库 `Dify/seekdb_service/seekdb_store.py` 里已有经过真实内核验证的建表语句可直接复用。

---

## 3. 部署配置

### 3.1 起 seekdb

```bash
docker run -d --name dify-seekdb -p 2881:2881 \\
  -e ROOT_PASSWORD="" -e CPU_COUNT=4 -e MEMORY_LIMIT=4G \\
  -v $PWD/.data/seekdb:/var/lib/oceanbase \\
  oceanbase/seekdb:latest
```

（仓库内也有等价编排：`Dify/seekdb_service/docker-compose.yml` 的 `seekdb` 服务。）

### 3.2 让 Dify 用上它

在 Dify 的 `docker/.env` 中把数据库指向 seekdb：

```dotenv
DB_USERNAME=root
DB_PASSWORD=
DB_HOST=seekdb          # 容器名，或宿主机 IP
DB_PORT=2881
DB_DATABASE=dify
DB_DRIVER=mysql
```

然后 `docker compose up -d` 起 Dify。初始化（建库 + 迁移）：

```bash
docker compose exec db sh -c "mysql -uroot -h127.0.0.1 -P3301 -e 'CREATE DATABASE IF NOT EXISTS dify DEFAULT CHARACTER SET utf8mb4'"
docker compose run --rm migrate
```

### 3.3 挂知识库（本作品的医书）

Dify 侧：知识库 → 创建 → 从文件导入 → 上传 `Dify/kb/*.md` → 索引方式选「高质量」。
Dify 侧的向量由 Dify 自己的 embedding provider 产生并**写入 seekdb**（此时 seekdb 承载
「知识库向量存储」）。

命令行一键完成（建库 + 上传文档 + 导入 DSL + 绑定）：

```bash
export DIFY_BASE_URL=https://cloud.dify.ai
export DIFY_API_KEY=app-xxxx          # 知识库 -> API -> Knowledge API key
export DIFY_CONSOLE_TOKEN=xxxx        # 浏览器 cookie
python Dify/scripts/setup_knowledge.py dataset
python Dify/scripts/setup_knowledge.py app --dataset-id <上一步输出的 id>
```

---

## 4. 实际读写验证步骤（评委可照此核对）

| # | 操作 | 命令 / 位置 | 期望 |
| --- | --- | --- | --- |
| 1 | Dify 写入一次对话 | 在 Dify 界面发一条消息 | seekdb 的 `conversations` / `messages` 表新增记录 |
| 2 | 直接查 seekdb | `SELECT COUNT(*) FROM conversations;` | 数量随使用增长 |
| 3 | 知识库向量落库 | `SELECT COUNT(*) FROM documents;`（或 `document_segments`） | >0，且 `embedding` 列非空 |
| 4 | 全文检索命中 | `SELECT id, LEFT(content,40) FROM document_segments WHERE ... MATCH ... AGAINST ('HNSW' IN NATURAL LANGUAGE MODE);` | 返回医书片段 |
| 5 | 向量检索命中 | 见 `Dify/seekdb_service/EVIDENCE_ROOT.json` 的 `vector_branch` 记录 | 返回最近邻片段与距离 |
| 6 | 应用数据（问诊/审查历史） | `SELECT COUNT(*) FROM qoder_review_log;` | 写入的应用历史条数 |

**我们自己的真实读写记录**（已随仓库交付）：

- `Dify/EVIDENCE_ROOT.json` —— 真实内核上的建表 / 写入 / 混合检索 / 写回历史记录
- `Dify/seekdb_service/EVIDENCE.json` —— 4 个真实查询的命中结果与检索计划（`_fts` + `_vs` 双分支）

---

## 5. 已知限制

- **Windows 嵌入式 seekdb**：`ORDER BY _distance APPROXIMATE`（HNSW 近似路径）在 Windows 的
  嵌入式绑定下不返回结果（同 `stepfun/TECH_REPORT.md` 记录的同一限制），
  因此本机演示走**混合计划路径**（`_fts` + `_vs` 双分支，RRF 融合，正常工作）；
  在 Linux / Docker 的 seekdb 服务端上，HNSW 近似路径同样可用（评测环境即为此形态）。
- **嵌入式模式不落盘**：Windows 嵌入式内核重启后数据为空，所以服务启动时会自动重新灌库
  （约 35 秒，19 块）。用 seekdb 服务端模式（`SEEKDB_HOST`）则数据持久化。
- **Dify + seekdb 同库**：Dify 会建自己的表；本作品的医书表建议单独建在同一个实例的
  独立 database（如 `dify_kb`），避免与 Dify 的迁移互相影响。
