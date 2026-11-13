# Qoder 赛题 · 运行说明（RUN.md）

> 评审按本文件从零跑起：**第 0 步就是主功能自检**，数秒内打印 `SELFCHECK PASS` 并退出码 0，
> 不需要 pip install、不需要网络、不需要 seekdb、不需要模型。

## 0. 主功能自检（默认入口，跑完即退出）

```bash
cd qoder
python run.py
```

实测输出（Python 3.9+，纯标准库）：

```text
[selfcheck] qoder-review-assistant / 零依赖主流程自检
[selfcheck] 规则引擎: reviewer.analyze() 已加载 15 条规则
[selfcheck] PASS  A 慢查询+深分页: error=0, warn=4, info=1
[selfcheck]        命中: OB-004, OB-005, OB-006, OB-007, OB-013
[selfcheck] PASS  A' 去掉函数包裹后 OB-006 消失: error=0, warn=3, info=1
[selfcheck]        命中: OB-004, OB-005, OB-007, OB-013
[selfcheck] PASS  B 全表 UPDATE: error=1, warn=0, info=0
[selfcheck]        命中: OB-001
[selfcheck] PASS  C 规则总数
SELFCHECK PASS (4/4 用例, 15 条规则)
[seekdb] SKIP  pylibseekdb 未安装 -> 跳过（主流程零依赖降级可用）
```

退出码 `0` 表示主流程（15 条规则引擎）实测通过；任一用例不符则打印 `SELFCHECK FAIL` 并返回非 0。
自检跑的就是主流程本身，不是另写一套假数据。

最后一行是 seekdb 集成自检：装了 `pylibseekdb` 时会真实跑一遍「建表 → 入库 → 检索 → 回写」，
输出 `[seekdb] PASS 规则知识 15 条入库；混合检索命中 N 条；审查历史 M 行写入`；
没装则 `SKIP`。**seekdb 自检无论成败都不影响主流程判定**，它跑在带硬超时的子进程里，
内核异常也不会把主自检拖挂。

## 1. 交互体验（常驻服务）

```bash
python run.py --serve          # -> http://127.0.0.1:8501
python run.py --port 9000      # 换端口，等价于 --serve
bash start.sh --serve            # 等价：自动找 python3/python 后同上
```

| 端点 | 说明 |
| --- | --- |
| `GET /` | 交互式审查界面（粘 SQL → 点「开始审查」→ 三级结果，与 Qoder Sites 页面同一套规则） |
| `GET /health` | `{"ok": true, "rules_loaded": 15, "seekdb": {...}}` |
| `GET /api/rules` | 15 条规则的 id / 级别 / 标题 |
| `POST /api/review` | `{"sql": "..."}` → findings + summary；装了内核时另带 `basis`（seekdb 检索到的判定依据）、`seekdb` 状态与 `review_id`（本轮写入 seekdb 的记录 id） |

```bash
curl -s localhost:8501/health
curl -s -X POST localhost:8501/api/review -H "Content-Type: application/json" \
  -d "{\"sql\": \"UPDATE orders SET status = 'ARCHIVED';\"}"
```

**首屏 1–2 秒内可用**：内核缺失时规则引擎照常工作（响应里会写明降级原因），
装了 `pylibseekdb` 时首次审查会拉起内嵌内核并做检索与回写。

## 2. 环境

| 项 | 版本 | 必需 |
| --- | --- | --- |
| Python | 3.9 ~ 3.13 | ✅（自检与服务都只用标准库） |
| streamlit | ≥1.32,<2 | ⭕（可选：完整 Streamlit 界面） |
| Docker + compose | 20.10+ | ⭕（可选） |
| CPU / 内存 | 2 核 / 4 GB | —（无 GPU 需求） |
| 推理服务 | 任意 OpenAI 兼容（MiniMax / StepFun / 魔搭 / 通义） | ⭕（不填则只跑规则层） |

## 3. 其它启动形态（都可选）

### A. 完整 Streamlit 界面

```bash
pip install -r requirements-ui.txt      # 仅 streamlit；主流程（python run.py）不需要装任何包
streamlit run app.py                    # 没装 streamlit 时 `python app.py` 会自动降级起 run.py 同款服务
```

### B. 真·seekdb + 本地 bge 向量

```bash
pip install -r requirements-seekdb.txt  # pylibseekdb / onnxruntime / tokenizers / numpy，全部宽松区间
python seekdb_service/fetch_model.py    # 取一次 bge-small-zh-v1.5 INT8 权重（约 23 MiB）
python run.py                           # 追加输出：[seekdb] PASS 规则知识 15 条入库；混合检索命中 N 条；审查历史 M 行写入
```

装了内核之后，每次审查都会（**内嵌内核直连，不需要另起 8848 服务**）：

1. 规则知识已存在真实表 `qoder_rule_knowledge`（`VECTOR(512)` + IK 全文索引 + HNSW 向量索引）；
2. 用 seekdb 内核做**向量 + 全文 + RRF** 混合检索，取回该条问题的判定依据，挂在 finding 的 `basis` 上；
3. 把本轮审查结果**写回 seekdb** 的 `qoder_review_log` 表，返回 `review_id`。

核对证据（真内核跑出来的文件，可一键重跑）：

```bash
python seekdb_service/capture_evidence.py   # -> EVIDENCE_ROOT.json
```

里面记着建表 DDL、写入行数、每次检索的计划是否同时含**全文分支**与**向量分支**、
命中的原文片段，以及审查历史写入的记录 id。

### C. Docker

```bash
docker compose up --build               # -> http://localhost:8501（容器内 CMD 为 run.py --serve）
docker compose --profile seekdb up -d   # 额外起 seekdb + 知识服务（带卷持久化）
```

## 4. 回归测试（不需要网络与其它依赖）

```bash
python tests/test_rules.py -v        # 23 passed（15 条规则各 1 组触发/不触发）
python tests/test_app_smoke.py -v    # 1 passed（UI 冒烟）
python smoke_test.py                 # PASS：启动 + 探活
```

## 5. 配置项

| 变量 | 用途 | 默认 |
| --- | --- | --- |
| `SEEKDB_PATH` | 内嵌 seekdb 数据目录 | `seekdb_service/.data/qoder-seekdb` |
| `SEEKDB_SERVICE_URL` | 知识服务地址（Streamlit 界面用） | `http://127.0.0.1:8848` |
| `MODELSCOPE_API_KEY` / `MINIMAX_API_KEY` / `STEPFUN_API_KEY` | 可选推理服务（OpenAI 兼容） | 空 |
| `MODELSCOPE_BASE_URL` / `MODELSCOPE_MODEL` | 推理地址与模型 | `https://api-inference.modelscope.cn/v1` / `Qwen/Qwen3.5-27B` |
| `SERVE` | 置为 `1` 等价于 `--serve` | 空 |

> 配置示例全部是占位值，仓库里**不含任何真实凭据**。

## 6. 项目网站

已发布：<https://sql-review-assistant-8ptbxy0nhc9.qoder.zone/>（未登录可访问，浏览器内可直接跑 15 条规则）。

## 7. 已知限制（如实说明）

- Windows 嵌入式 seekdb 的 HNSW 近似路径不返回结果（与 `stepfun/TECH_REPORT.md` 同一限制），
  混合检索计划路径（`_fts` + `_vs` + RRF）正常；Linux / Docker 服务端上两条路径都可用。
- 嵌入式模式不跨重启持久（Windows 绑定限制）；seekdb 服务端模式持久化。
- 模型权重不入库（23 MiB）：`fetch_model.py` 取一次；取不到时退回确定性哈希向量，
  seekdb 的存储、HNSW 索引、向量分支与 RRF 融合依然完整可用。
