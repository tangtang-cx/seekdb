# AMD ROCm / hipVS（cuVS CAGRA）加速 HNSW 索引构建

> 结论来源：`amd/docs/PERF_NOTES.md`（团队在 `amd-cagra-solution` 分支的实现与推演）。
> 注意：本机是 NVIDIA GB10（ARM64 + CUDA 13），无 `/dev/kfd`、无 ROCm 与 hipVS，
> 因此以下收益为**模型估算**，必须在 AMD 机器上复跑确认。

## 1. 赛题硬门槛

评测要求 **GPU CAGRA 路径**：必须走 `hipVS`（AMD 对 cuVS 的移植），
纯 CPU 平替不作为有效提交，且需要与同轮官方基线对比：

- 建图加速 ≥ 3.0x；
- 查询加速 ≥ 1.5x；
- recall 与同轮基线相差 ≤ 0.005。

## 2. 官方冻结基线（commit `634888d9`）

| 项目 | 基线 |
| --- | --- |
| 建图算法 | `NN_DESCENT` |
| `graph_degree` | 128 |
| `intermediate_graph_degree` | 256 |
| `nn_descent_niter` | 100 |
| 数据集传递 | `kDLCPU` 主机张量，cuVS 内部再拷到显存 |
| 查询设备缓冲 | 每次调用 `cuvsRMMAlloc/Free` ×3 |
| 查询参数 | 每次调用 `cuvsCagraSearchParamsCreate/Destroy` |
| 查询线程 | adaptor 每次查询新建 32MB pthread |
| 查询结果回传 | pageable `cudaMemcpy` |

## 3. 优化点与预期收益

| 项目 | 优化后 | 收益来源 |
| --- | --- | --- |
| `graph_degree` | 96（可覆盖） | 建图主循环计算量下降 |
| `intermediate_graph_degree` | 144（可覆盖） | 中间图规模下降 |
| `nn_descent_niter` | 40（可覆盖） | 迭代次数下降 |
| 数据集传递 | `cuvsRMMAlloc` 设备缓冲 + `kDLCUDA` DLPack 张量 | 避免重复 H2D 拷贝 |
| 查询设备缓冲 | 按 handle 分配一次，随 `nq`/`topk` 增长复用 | 移出热路径 |
| 查询参数 | `topk` 缓存复用 | 移出热路径 |
| 查询线程 | bridge 内部常驻 32MB worker | 去掉每查询 pthread create/join |
| 结果回传 | 复用 `cudaMallocHost` pinned 缓冲 | pageable → pinned 拷贝 |

建图收益模型（NN-Descent 计算量 ≈ `niter × graph_degree`）：

```text
baseline:  100 × 128 = 12800
optimized:  40 ×  96 =  3840
ratio:      12800 / 3840 = 3.33x
```

实测还要叠加 CAGRA 内部固定开销、数据传输与 GPU 利用率影响，
团队预估整体 **2.8x ~ 3.5x**，覆盖 3.0x 门槛。

## 4. 风险控制：recall 红线

降低 `graph_degree` / `niter` 会损失 recall，硬门槛是「与同轮基线相差 ≤ 0.005」。
建议按以下顺序扫描（每次只改一档）：

| 档位 | degree | intermediate | niter | 预期构建 | 风险 |
| --- | --- | --- | --- | --- | --- |
| 安全 | 112 | 168 | 48 | ~2.4x | recall 最稳 |
| 默认 | 96 | 144 | 40 | ~3.0x | 推荐先测 |
| 激进 | 80 | 120 | 32 | ~4.0x | recall 可能贴近红线 |
| 极激进 | 64 | 96 | 24 | ~5.3x | 仅在前两档 recall 余量很大时使用 |

查询侧 `search_width` 默认 4；recall 有余量且要吞吐可试 2（`itopk_size` 仍保持 ≥ 12）。

## 5. 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SEEKDB_CUVS_GRAPH_DEGREE` | 96 | CAGRA 输出图度 |
| `SEEKDB_CUVS_INTERMEDIATE_GRAPH_DEGREE` | 144 | 中间图度数，必须 ≥ degree |
| `SEEKDB_CUVS_NITER` | 40 | NN-Descent 迭代次数 |
| `SEEKDB_CUVS_SEARCH_WIDTH` | 4 | CAGRA 搜索宽度 |
| `SEEKDB_CUVS_MAX_QUERIES` | 0 | 0 = 自动 batch |
| `SEEKDB_CUVS_BUILD_ALGO` | `nn_descent` | `nn_descent` / `auto` / `iterative` |
| `SEEKDB_CUVS_PIN_BUILD_INPUT` | 1 | 建图前尝试 `cudaHostRegister` |
| `SEEKDB_CUVS_VERBOSE` | 0 | 打印实际使用的构建参数 |

建图参数在 `seekdb_cuvs_build` 时读取并缓存 env，改 env 后需要 reload bridge。

## 6. 复跑步骤（AMD 机器）

```bash
git clone https://github.com/zihaomu/seekdb.git
cd seekdb
git checkout amd-oceanbase-official-contest-base-v5   # 634888d9b037153fa143d2c913ba4b25503e1d62
bash /path/to/ai-ecosystem/amd/scripts/apply_to_seekdb.sh --seekdb "$PWD" --with-adaptor-patch
# 按官方文档编译 observer（OB_BUILD_CUVS=ON + bridge 路径）
bash docs/gpu-vector-index-hipvs-cuvs/validation/run_gpu_smoke.sh ...
```

必测用例：recall 用例（与同轮基线对比）、建图耗时、QPS、并发查询、快照与边界用例。
