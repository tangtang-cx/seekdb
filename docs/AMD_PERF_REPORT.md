# AMD hipVS CAGRA 优化报告

## 1. 基线与提交

| 项目 | 值 |
| --- | --- |
| 基线仓库 | `https://github.com/zihaomu/seekdb` |
| 基线分支 | `amd-oceanbase-official-contest-base-v5` |
| 基线 commit | `634888d9b037153fa143d2c913ba4b25503e1d62` |
| 本分支 | `amd-cagra-submit`（基于上述基线） |
| 目标硬件 | AMD Radeon PRO W7900D 48GB，ROCm 7.2.4，hipVS 26.03 |

本报告只记录改动、方法和复跑命令。**数字以提测平台/AMD 机器实测为准**；本机
没有 AMD GPU/ROCm/hipVS，未伪造任何 AMD 性能或 recall 数据。

## 2. 改动范围

| 文件 | 说明 |
| --- | --- |
| `tools/hipvs_bridge/seekdb_cuvs_bridge.c` | CAGRA build/search 优化实现 |
| `tools/hipvs_bridge/build.sh` | `-O3 -DNDEBUG -pthread`，其余与基线一致 |
| `src/oblib/lib/vector/ob_vsag_adaptor.cpp` | 去掉每查询一次的 pthread（bridge 内部已有常驻大栈 worker） |
| `tools/hipvs_bridge/bench_bridge.py` | bridge 级 build/QPS/recall 基准脚本 |
| `tools/hipvs_bridge/0001-ob-vsag-adaptor-direct-search.patch` | adaptor 改动的独立 patch（便于回滚） |

导出的 6 个 C 符号和 `seekdb_cuvs_bridge.h` 与基线完全一致，observer 不需要改
链接参数。

## 3. 优化方法

### 3.1 建图参数

| 参数 | 基线 | 优化版 |
| --- | --- | --- |
| build algo | `NN_DESCENT` | `NN_DESCENT` |
| `graph_degree` | 128 | 96 |
| `intermediate_graph_degree` | 256 | 144 |
| `nn_descent_niter` | 100 | 40 |

NN-Descent 主循环计算量近似正比于 `niter × graph_degree`：

```text
baseline:  100 × 128 = 12800
optimized:  40 ×  96 =  3840
ratio:      12800 / 3840 = 3.33x
```

这是理论上限，实际还要算上固定开销和 H2D；预计整体 2.8x–3.5x。默认值可通过
环境变量覆盖，便于在 AMD 机器上按 recall 余量扫描。

### 3.2 避免重复 H2D

基线把 `base` 包装成 `kDLCPU` 张量，由 `cuvsCagraBuild` 内部再分配显存并拷贝。
优化版先 `cuvsRMMAlloc` 设备缓冲，直接以 `kDLCUDA` 张量建图：

- 用 `cuvsCagraIndexGetDataset` 判断 index 是否复用我们的缓冲；
- 复用则 handle 持有该显存到 `seekdb_cuvs_free`；
- 内部另拷贝则建图后立即释放，不增加常驻显存；
- 建图前尝试 `cudaHostRegister`，失败则退回普通 pageable H2D。

### 3.3 查询热路径

基线每次查询都会：

1. `cuvsRMMAlloc/Free` ×3；
2. `cuvsCagraSearchParamsCreate/Destroy`；
3. adaptor 里 `pthread_create/join`（32MB 栈）；
4. pageable 结果拷贝。

优化版按 handle 缓存设备查询/结果缓冲、pinned 结果缓冲和 search params；查询由
常驻 32MB 栈 worker 执行；结果先到 pinned 缓冲再 `memcpy`。`cudaDeviceSynchronize`
显式等待 CAGRA 内部 stream，避免不同 hipVS 版本的隐式同步差异。

`search_width` 默认 4，`itopk_size` 至少 `max(512, topk*4)`（不超过 n），保持
recall 余量。

## 4. Recall 风险

硬门槛是相对同轮基线 recall 下降 ≤0.005：

- SIFT250K（128d）基线 1.000 → 需 ≥0.995；
- 隐藏 250K×256 基线 0.985/0.914 → 需 ≥0.980/0.909。

默认 `96/144/40` 是保守档。若平台 recall 贴近红线，按以下顺序回退（每次只改一档）：

| 档位 | degree | intermediate | niter | 说明 |
| --- | --- | --- | --- | --- |
| 安全 | 112 | 168 | 48 | 优先保 recall |
| 默认 | 96 | 144 | 40 | 提交默认值 |
| 激进 | 80 | 120 | 32 | 仅在 recall 余量充足时 |

## 5. 复跑与证据

```bash
# 1) 确认在冻结基线后代上
git merge-base --is-ancestor 634888d9b037153fa143d2c913ba4b25503e1d62 HEAD

# 2) 编译 bridge
HIPVS_ROOT=/opt/hipvs ROCM_ROOT=/opt/rocm bash tools/hipvs_bridge/build.sh

# 3) bridge 级基准（参数扫描/recall）
python3 tools/hipvs_bridge/bench_bridge.py \
  --bridge ./tools/hipvs_bridge/libseekdb_cuvs_bridge.so \
  --n 250000 --dim 128 --nq 4096 --topk 10 --single-row \
  --json /tmp/sift250k.json --label default

# 4) 基线对照：显式设回 128/256/100 后重跑
SEEKDB_CUVS_GRAPH_DEGREE=128 \
SEEKDB_CUVS_INTERMEDIATE_GRAPH_DEGREE=256 \
SEEKDB_CUVS_NITER=100 \
python3 tools/hipvs_bridge/bench_bridge.py ...
```

必须记录：`build_seconds`（3 次中位数）、recall@10/100、批量/单行 QPS、显存峰值、
`SEEKDB_CUVS_VERBOSE=1` 的参数日志。任何一项硬门槛不过，先回退参数档，不要带病提交。

## 6. 回滚

```bash
# 参数回退
export SEEKDB_CUVS_GRAPH_DEGREE=128
export SEEKDB_CUVS_INTERMEDIATE_GRAPH_DEGREE=256
export SEEKDB_CUVS_NITER=100

# adaptor 回退
git apply -R tools/hipvs_bridge/0001-ob-vsag-adaptor-direct-search.patch
```

## 7. 本地验证边界

- bridge 已用 hipVS 26.03 头文件做 `gcc -fsyntax-only` 检查；
- 用 fake cuVS（CPU 暴力 L2）+ 真实 CUDA runtime 跑通单查询、批量、4 线程并发、
  序列化/反序列化、one-shot 和 `topk>n` 保护；
- 覆盖 index 复用输入缓冲、index 内部复制、`GetDataset` 失败三种所有权分支；
- 这些只证明线程/内存/所有权逻辑，**不证明** AMD 上的真 cuVS 性能与 recall。
