# Dify 赛题 · 运行说明（RUN.md）

> **本文档描述的是可选增强，不是评测对象。**
> 主交付是 `app.yml`（workflow：开始 → 规则体检 code 节点 → 出方），
> **不需要 seekdb、不需要模型、不需要外部服务**。下面这套 seekdb 检索增强
> 只在你想看「真·向量检索」时使用，评测时可以完全忽略。

> 评审按本文件从零跑起，即可体验作品的主要功能。

## 0. 一句话

```bash
cd dify
pip install -r requirements.txt      # 只有 streamlit，不写死版本
streamlit run app.py                # -> http://localhost:8501
```

**首屏 2 秒内可用**（seekdb 服务在后台自动拉起；拉不起来也不影响使用）。

## 1. 环境

| 项 | 版本 | 必需 |
| --- | --- | --- |
| Python | 3.9 ~ 3.13 | ✅ |
| streamlit | ≥1.32,<2 | ✅（唯一必装依赖） |
| Docker + docker compose | 20.10+ | ⭕（可选，用服务端的 seekdb） |
| CPU / 内存 | 2 核 / 4 GB | —（无 GPU 需求，bge 为 INT8 ONNX） |
| 模型服务 | 任意 OpenAI 兼容（通义 / DeepSeek / MiniMax / StepFun / 魔搭） | ⭕（不填也能用，见 §4） |

## 2. 三种启动形态

### A. 最简（只装 streamlit）

```bash
pip install -r requirements.txt
streamlit run app.py
```

功能：规则引擎 + （若配了 Key）大模型深审。seekdb 不可用时页面会提示，但**不影响使用**。

### B. 完整（真·seekdb + 本地 bge 向量）

```bash
pip install -r requirements-seekdb.txt          # pylibseekdb / onnxruntime / tokenizers / numpy，全部宽松区间
python seekdb_service/fetch_model.py            # 取一次 bge-small-zh-v1.5 INT8 权重（约 23 MiB）
streamlit run app.py                            # 后台自动拉起 seekdb 知识服务（8848）
```

此时：
- 审查依据来自 seekdb 的**向量 + 全文 + RRF** 混合检索（融合在 seekdb 内核内完成）；
- 每轮审查结果**写回 seekdb** 的 `qoder_review_log` 表，界面可实时查回历史。

### C. Docker（带持久化卷）

```bash
docker compose -f deploy/docker-compose.yml up -d
curl http://127.0.0.1:8848/health    # {"ok":true,"chunks":19,...}
```

`deploy/docker-compose.yml` 里 seekdb 用**持久化卷** + `healthcheck`，知识服务 `depends_on: service_healthy`
（避免「web 早于 DB 启动」的竞态）。

## 3. 导入 Dify 应用（三选一，按评测环境）

| 文件 | 何时用 | 依赖 |
| --- | --- | --- |
| `app.yml` | **主交付**。工作区有可用模型时用（模型 `tongyi/qwen-plus`） | 需要工作区配置了通义 |
| `app-nomodel.yml` | 工作区**没有模型**时用：**不依赖任何模型供应商**，模板节点固定输出六段 | 无 |
| `variants/app-with-model.yml` | 需要写死通义模型时用 | 通义 Key |
| `variants/app-seekdb.yml` | 自建 Dify + 本机 seekdb 服务（HTTP 节点取医书原文） | seekdb 服务可达 |

导入步骤：Studio → 创建应用 → **导入 DSL 文件** → 上传对应 `.yml` → 知识检索/模型节点按需确认 → 发布 → 分享。

## 4. 没有模型 / 模型调用失败时

`app-nomodel.yml` 用模板节点把「📖 医书摘录 / 🩺 望闻问切 / 💊 药方 / 🚫 忌口 / 🧘 养生建议 / 🎋 医嘱小笺」
六段固定输出，并把输入的 SQL 逐条对照 15 条规则给出结论 —— **不依赖模型也能接收输入并返回结果**。

## 5. 自检（不需要网络与其它依赖）

```bash
python smoke_test.py                # PASS：能启动并探活
python seekdb_service/verify.py      # 真 seekdb 内核 + 真向量 + 混合检索命中
python scripts/validate_dsl.py app.yml app-nomodel.yml variants/app-with-model.yml variants/app-seekdb.yml
```

## 6. 配置项

| 变量 | 用途 | 默认 |
| --- | --- | --- |
| `SEEKDB_SERVICE_URL` | 知识服务地址 | `http://127.0.0.1:8848` |
| `SEEKDB_HOST` / `SEEKDB_PORT` / `SEEKDB_USER` / `SEEKDB_PASSWORD` | seekdb 服务端 | `seekdb` / `2881` / `root` / 空 |
| `BGE_MODEL_DIR` | 模型权重目录 | `stepfun/public/models/bge-small-zh-v1.5` |
| `MODELSCOPE_API_KEY` / `MINIMAX_API_KEY` / `STEPFUN_API_KEY` | 可选推理服务 | 空（不填也能用） |

> 配置示例全部是占位值，仓库里**不含任何真实凭据**。

## 7. 已知限制（如实说明）

- **Windows 嵌入式 seekdb**：`ORDER BY _distance APPROXIMATE`（HNSW 近似路径）在 Windows 绑定下不返回结果
  （与 `stepfun/TECH_REPORT.md` 记录的同一限制）；因此 Windows 演示走混合计划路径
  （`_fts` + `_vs` 双分支 + RRF 融合，正常工作）。Linux / Docker 的 seekdb 服务端上 HNSW 近似路径同样可用。
- **嵌入式模式不跨重启持久**：Windows 嵌入式内核重启后数据为空，服务启动时会自动重新灌库（约 35 秒 / 19 块）；
  用 seekdb **服务端**模式则持久化（见 §2.C 的卷配置）。
- **模型权重不入库**（23 MiB 太大）：`fetch_model.py` 取一次；取不到时自动降级为确定性字符 n-gram 哈希向量
  （512 维、L2 归一化），seekdb 的存储、HNSW 索引、向量分支与 RRF 融合**依然完整可用**。
