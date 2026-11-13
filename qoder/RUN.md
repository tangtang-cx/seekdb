# Qoder 赛题 · 运行说明（RUN.md）

> 评审按本文件从零跑起，即可体验作品的主要功能。

## 0. 一句话

```bash
cd qoder
pip install -r requirements.txt      # 只有 streamlit，不写死版本
streamlit run app.py                # -> http://localhost:8501
```

**首屏 2 秒内可用**：seekdb 知识服务在后台自动拉起；拉不起来也不影响使用
（规则引擎照常工作，只是没有「医书依据」与历史落库）。

## 1. 环境

| 项 | 版本 | 必需 |
| --- | --- | --- |
| Python | 3.9 ~ 3.13 | ✅ |
| streamlit | ≥1.32,<2 | ✅（唯一必装依赖） |
| Docker + compose | 20.10+ | ⭕（可选） |
| CPU / 内存 | 2 核 / 4 GB | —（无 GPU 需求） |
| 推理服务 | 任意 OpenAI 兼容（MiniMax / StepFun / 魔搭 / 通义） | ⭕（不填则只跑规则层） |

## 2. 三种启动形态

### A. 最简（只装 streamlit）

```bash
pip install -r requirements.txt
streamlit run app.py
```

### B. 完整（真·seekdb + 本地 bge 向量）

```bash
pip install -r requirements-seekdb.txt          # pylibseekdb / onnxruntime / tokenizers / numpy，全部宽松区间
python seekdb_service/fetch_model.py            # 取一次 bge-small-zh-v1.5 INT8 权重（约 23 MiB）
streamlit run app.py                            # 后台自动拉起 seekdb 知识服务（8848）
```

此时每次审查都会：
1. 用 seekdb 做**向量 + 全文 + RRF** 混合检索（融合在 seekdb 内核内完成）取回「医书」依据；
2. 把本轮审查结果**写回 seekdb** 的 `qoder_review_log` 表；
3. 界面上的「seekdb 里的审查历史」是实时从 seekdb 查出来的。

### C. Docker

```bash
docker compose up --build              # -> http://localhost:8501
docker compose --profile seekdb up -d   # 额外起 seekdb + 知识服务（带卷持久化）
```

## 3. 自检（不需要网络与其它依赖）

```bash
python tests/test_rules.py -v        # 22 passed（15 条规则各 1 组触发/不触发）
python tests/test_app_smoke.py -v    # 1 passed（UI 冒烟）
python smoke_test.py                 # PASS：启动 + 探活
```

## 4. 配置项

| 变量 | 用途 | 默认 |
| --- | --- | --- |
| `SEEKDB_SERVICE_URL` | 知识服务地址 | `http://127.0.0.1:8848` |
| `MODELSCOPE_API_KEY` / `MINIMAX_API_KEY` / `STEPFUN_API_KEY` | 可选推理服务（OpenAI 兼容） | 空 |
| `MODELSCOPE_BASE_URL` / `MODELSCOPE_MODEL` | 推理地址与模型 | `https://api-inference.modelscope.cn/v1` / `Qwen/Qwen3.5-27B` |

> 配置示例全部是占位值，仓库里**不含任何真实凭据**。

## 5. 项目网站

已发布：<https://sql-review-assistant-8ptbxy0nhc9.qoder.zone/>（未登录可访问，浏览器内可直接跑 15 条规则）。

## 6. 已知限制（如实说明）

- Windows 嵌入式 seekdb 的 HNSW 近似路径不返回结果（与 `stepfun/TECH_REPORT.md` 同一限制），
  混合检索计划路径（`_fts` + `_vs` + RRF）正常；Linux / Docker 服务端上两条路径都可用。
- 嵌入式模式不跨重启持久（Windows 绑定限制）；seekdb 服务端模式持久化。
- 模型权重不入库（23 MiB）：`fetch_model.py` 取一次；取不到时退回确定性哈希向量，
  seekdb 的存储、HNSW 索引、向量分支与 RRF 融合依然完整可用。
