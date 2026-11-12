#!/usr/bin/env python3
"""Benchmark the seekdb hipVS CAGRA bridge directly (no seekdb server needed).

Run this on the AMD/ROCm box after building libseekdb_cuvs_bridge.so.  It
measures the same quantities as the contest harness at the bridge level:
build wall time, batched QPS, single-row QPS and recall@k.

Example:
  python3 bench_bridge.py --bridge ./libseekdb_cuvs_bridge.so \
      --build-script ../solution/build.sh \
      --n 250000 --dim 128 --nq 4096 --topk 10 \
      --graph-degree 96 --intermediate-degree 144 --niter 40 \
      --json ../results/sift250k_opt.json --label opt

  # baseline for comparison
  python3 bench_bridge.py --bridge ./libseekdb_cuvs_bridge.so \
      --graph-degree 128 --intermediate-degree 256 --niter 100 \
      --json ../results/sift250k_baseline.json --label baseline

The bridge reads tuning knobs from the environment at build time; this script
sets them before calling --build-script (or expects a pre-built .so).
"""

import argparse
import ctypes
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

try:
    import numpy as np
except ImportError:
    sys.exit("numpy is required: python3 -m pip install numpy")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bridge", required=True, help="path to libseekdb_cuvs_bridge.so")
    p.add_argument("--build-script", default=None,
                   help="optional build.sh to run before loading the bridge")
    p.add_argument("--n", type=int, default=250_000)
    p.add_argument("--dim", type=int, default=128)
    p.add_argument("--nq", type=int, default=4096)
    p.add_argument("--topk", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--warmup", type=int, default=3)
    p.add_argument("--single-row", action="store_true",
                   help="also measure 4096 separate 1-row searches")
    p.add_argument("--recall-queries", type=int, default=200,
                   help="subset size for exact recall; 0 disables recall")
    p.add_argument("--base-npy", default=None, help="optional real base vectors (.npy, n x dim f32)")
    p.add_argument("--query-npy", default=None, help="optional real query vectors (.npy)")
    p.add_argument("--gt-npy", default=None, help="optional exact neighbor ids (.npy, m x topk)")
    p.add_argument("--graph-degree", type=int, default=None)
    p.add_argument("--intermediate-degree", type=int, default=None)
    p.add_argument("--niter", type=int, default=None)
    p.add_argument("--search-width", type=int, default=None)
    p.add_argument("--json", default=None)
    p.add_argument("--label", default="run")
    return p.parse_args()


def set_env(args):
    env = os.environ.copy()
    pairs = [
        ("SEEKDB_CUVS_GRAPH_DEGREE", args.graph_degree),
        ("SEEKDB_CUVS_INTERMEDIATE_GRAPH_DEGREE", args.intermediate_degree),
        ("SEEKDB_CUVS_NITER", args.niter),
        ("SEEKDB_CUVS_SEARCH_WIDTH", args.search_width),
    ]
    for name, value in pairs:
        if value is not None:
            env[name] = str(value)
    env.setdefault("SEEKDB_CUVS_VERBOSE", "1")
    return env


def load_bridge(path):
    lib = ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
    lib.seekdb_cuvs_build.argtypes = [ctypes.POINTER(ctypes.c_float),
                                      ctypes.c_long, ctypes.c_long]
    lib.seekdb_cuvs_build.restype = ctypes.c_void_p
    lib.seekdb_cuvs_search.argtypes = [ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_float),
                                       ctypes.c_long, ctypes.c_long,
                                       ctypes.POINTER(ctypes.c_uint),
                                       ctypes.POINTER(ctypes.c_float)]
    lib.seekdb_cuvs_search.restype = ctypes.c_int
    lib.seekdb_cuvs_free.argtypes = [ctypes.c_void_p]
    lib.seekdb_cuvs_free.restype = None
    return lib


def make_data(args):
    rng = np.random.default_rng(args.seed)
    if args.base_npy:
        base = np.load(args.base_npy, mmap_mode=None)
        base = np.ascontiguousarray(base, dtype=np.float32)
    else:
        base = rng.standard_normal((args.n, args.dim), dtype=np.float32)
    if args.query_npy:
        queries = np.load(args.query_npy)
        queries = np.ascontiguousarray(queries, dtype=np.float32)
    else:
        queries = rng.standard_normal((args.nq, args.dim), dtype=np.float32)
    return base, queries


def exact_topk(base, queries, k, chunk=64):
    """Exact L2 top-k on CPU, chunked to keep the distance matrix small."""
    out = np.empty((queries.shape[0], k), dtype=np.uint32)
    b = np.ascontiguousarray(base, dtype=np.float32)
    base_sq = np.einsum("ij,ij->i", b, b)
    for start in range(0, queries.shape[0], chunk):
        q = np.ascontiguousarray(queries[start:start + chunk], dtype=np.float32)
        q_sq = np.einsum("ij,ij->i", q, q)
        dist = q_sq[:, None] + base_sq[None, :] - 2.0 * (q @ b.T)
        part = np.argpartition(dist, k - 1, axis=1)[:, :k]
        rows = np.arange(part.shape[0])[:, None]
        order = np.argsort(dist[rows, part], axis=1)
        out[start:start + chunk] = part[rows, order]
    return out


def recall_at_k(got, truth):
    total = 0.0
    k = truth.shape[1]
    for i in range(truth.shape[0]):
        total += len(set(got[i].tolist()) & set(truth[i].tolist())) / float(k)
    return total / float(truth.shape[0])


def timed_search(lib, handle, queries, topk, n):
    nq = queries.shape[0]
    out_ids = np.empty((nq, topk), dtype=np.uint32)
    out_dist = np.empty((nq, topk), dtype=np.float32)
    t0 = time.perf_counter()
    rc = lib.seekdb_cuvs_search(
        handle,
        queries.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        nq, topk,
        out_ids.ctypes.data_as(ctypes.POINTER(ctypes.c_uint)),
        out_dist.ctypes.data_as(ctypes.POINTER(ctypes.c_float)))
    elapsed = time.perf_counter() - t0
    if rc != 0:
        raise RuntimeError(f"seekdb_cuvs_search failed: rc={rc}")
    invalid = int(np.count_nonzero(out_ids >= n))
    if invalid:
        raise RuntimeError(f"bridge returned {invalid} out-of-range ids (n={n})")
    return elapsed, out_ids, out_dist, invalid


def main():
    args = parse_args()
    env = set_env(args)
    bridge = Path(args.bridge).resolve()
    if args.build_script:
        print(f"[bench] building {bridge} with {args.build_script}", flush=True)
        subprocess.run(["bash", args.build_script, str(bridge)], check=True, env=env)
    if not bridge.exists():
        sys.exit(f"bridge not found: {bridge}")

    base, queries = make_data(args)
    n, dim = base.shape
    nq = queries.shape[0]
    if queries.shape[1] != dim:
        sys.exit(f"dim mismatch: base {dim}, queries {queries.shape[1]}")
    topk = min(args.topk, n)

    print(f"[bench] n={n} dim={dim} nq={nq} topk={topk} label={args.label}", flush=True)
    lib = load_bridge(bridge)

    t0 = time.perf_counter()
    handle = lib.seekdb_cuvs_build(
        base.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), n, dim)
    build_s = time.perf_counter() - t0
    if not handle:
        sys.exit("seekdb_cuvs_build returned NULL")
    print(f"[bench] build {build_s:.3f}s", flush=True)

    try:
        # Warm up workspace + params + worker thread.
        for _ in range(max(1, args.warmup)):
            timed_search(lib, handle, np.ascontiguousarray(queries[:1]), topk, n)
        if args.single_row:
            for _ in range(max(1, args.warmup)):
                for i in range(min(8, nq)):
                    timed_search(lib, handle, np.ascontiguousarray(queries[i:i + 1]), topk, n)

        batch_times = []
        last_ids = None
        for _ in range(max(1, args.repeat)):
            elapsed, ids, _dist, _ = timed_search(lib, handle, queries, topk, n)
            batch_times.append(elapsed)
            last_ids = ids
        batch_best = min(batch_times)
        batch_med = statistics.median(batch_times)

        single = None
        if args.single_row:
            t0 = time.perf_counter()
            for i in range(nq):
                timed_search(lib, handle, np.ascontiguousarray(queries[i:i + 1]), topk, n)
            single_s = time.perf_counter() - t0
            single = {"seconds": single_s, "qps": nq / single_s}

        recall = None
        if args.recall_queries and args.recall_queries > 0:
            m = min(args.recall_queries, nq)
            if args.gt_npy:
                truth = np.load(args.gt_npy)[:m, :topk].astype(np.uint32)
            else:
                print(f"[bench] exact top-{topk} for {m} queries on CPU ...", flush=True)
                truth = exact_topk(base, queries[:m], topk)
            elapsed, got, _dist, _ = timed_search(
                lib, handle, np.ascontiguousarray(queries[:m]), topk, n)
            recall = recall_at_k(got, truth)
            print(f"[bench] recall@{topk} = {recall:.6f} ({elapsed:.3f}s)", flush=True)

        result = {
            "label": args.label,
            "bridge": str(bridge),
            "n": n,
            "dim": dim,
            "nq": nq,
            "topk": topk,
            "params": {
                "graph_degree": args.graph_degree,
                "intermediate_graph_degree": args.intermediate_degree,
                "niter": args.niter,
                "search_width": args.search_width,
            },
            "build_seconds": build_s,
            "batch": {
                "times": batch_times,
                "best_seconds": batch_best,
                "median_seconds": batch_med,
                "qps_best": nq / batch_best,
                "qps_median": nq / batch_med,
            },
            "single_row": single,
            "recall_at_k": recall,
        }
        text = json.dumps(result, indent=2, sort_keys=True)
        print(text)
        if args.json:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + "\n")
            print(f"[bench] wrote {out}")
    finally:
        lib.seekdb_cuvs_free(handle)


if __name__ == "__main__":
    main()
