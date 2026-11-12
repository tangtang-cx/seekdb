/*
 * seekdb <-> hipVS bridge: plain-C CAGRA kNN; all cuVS/ROCm deps live here.
 *
 * Optimized for the AMD hipVS contest baseline.  The exported ABI is identical
 * to tools/hipvs_bridge/seekdb_cuvs_bridge.c; only the implementation changed.
 *
 * Main differences vs. the baseline:
 *   - CAGRA build parameters are tuned (96/144/40 by default, env-overridable)
 *     instead of 128/256/100, which is the dominant build-time win.
 *   - The dataset is handed to cuVS as a device tensor, avoiding an extra
 *     implicit host->device copy inside cuvsCagraBuild (when the index keeps
 *     the buffer we keep it alive; otherwise it is released right away).
 *   - All per-query device buffers/cudaMallocHost buffers and the CAGRA search
 *     params are allocated once per handle and reused.
 *   - Search runs on a persistent 32MB-stack worker thread (cuVS overflows the
 *     small seekdb worker stack), so callers no longer need a pthread per query.
 *   - Build also runs on a temporary 32MB-stack worker, so any caller stack is
 *     safe even without the seekdb adaptor patch.
 *
 * Environment knobs (all optional):
 *   SEEKDB_CUVS_GRAPH_DEGREE, SEEKDB_CUVS_INTERMEDIATE_GRAPH_DEGREE,
 *   SEEKDB_CUVS_NITER, SEEKDB_CUVS_SEARCH_WIDTH, SEEKDB_CUVS_BUILD_ALGO,
 *   SEEKDB_CUVS_PIN_BUILD_INPUT=0, SEEKDB_CUVS_VERBOSE=1
 */
#define _GNU_SOURCE
#include "seekdb_cuvs_bridge.h"
#include <cuvs/core/c_api.h>
#include <cuvs/neighbors/cagra.h>
#include <dlpack/dlpack.h>
#ifdef __HIP_PLATFORM_AMD__
#include <cuvs/cuda_runtime.h>
#else
#include <cuda_runtime.h>
#endif
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SK_BIG_STACK (32UL * 1024UL * 1024UL)
#define SK_DEFAULT_GRAPH_DEGREE 96
#define SK_DEFAULT_INTERMEDIATE_GRAPH_DEGREE 144
#define SK_DEFAULT_NITER 40
#define SK_DEFAULT_SEARCH_WIDTH 4

typedef struct sk_cuvs_index {
  cuvsResources_t res;
  cuvsCagraIndexParams_t ip;
  cuvsCagraIndex_t idx;
  long n, dim;

  /* Device dataset owned by this handle, only when CAGRA keeps our buffer. */
  void* dev_dataset;
  size_t dev_dataset_bytes;
  int owns_dev_dataset;

  /* Serializes all cuVS calls (search worker / serialize / free). */
  pthread_mutex_t exec_mu;

  /* Reused search state. */
  cuvsCagraSearchParams_t sp;
  size_t sp_topk;
  void* dev_q;
  size_t dev_q_cap;
  void* dev_ids;
  size_t dev_ids_cap;
  void* dev_dist;
  size_t dev_dist_cap;
  unsigned* host_ids;
  size_t host_ids_cap;
  float* host_dist;
  size_t host_dist_cap;

  /* Persistent big-stack search worker. */
  pthread_mutex_t q_mu;
  pthread_cond_t q_work_cv;
  pthread_cond_t q_done_cv;
  int worker_started;
  int quit;
  int busy;
  pthread_t worker;
  struct {
    const float* query;
    long nq;
    long topk;
    unsigned* out_ids;
    float* out_dist;
    int rc;
  } job;
} sk_cuvs_index;

static const char* sk_err(void)
{
  const char* e = cuvsGetLastErrorText();
  return (e != NULL) ? e : "(no cuVS error text)";
}

static long sk_env_long(const char* name, long def)
{
  const char* s = getenv(name);
  char* end = NULL;
  long v;
  if (s == NULL || *s == '\0') { return def; }
  v = strtol(s, &end, 10);
  return (end == s) ? def : v;
}

static int sk_env_flag(const char* name, int def)
{
  const char* s = getenv(name);
  if (s == NULL || *s == '\0') { return def; }
  if (s[0] == '1' || s[0] == 't' || s[0] == 'T' || s[0] == 'y' || s[0] == 'Y') { return 1; }
  if (s[0] == '0' || s[0] == 'f' || s[0] == 'F' || s[0] == 'n' || s[0] == 'N') { return 0; }
  return def;
}

static int sk_mul_size(size_t a, size_t b, size_t c, size_t* out)
{
  size_t t;
  if (a != 0 && b > SIZE_MAX / a) { return -1; }
  t = a * b;
  if (t != 0 && c > SIZE_MAX / t) { return -1; }
  *out = t * c;
  return 0;
}

static void sk_tensor(DLManagedTensor* t, void* data, int64_t* shape,
                      DLDataTypeCode code, int bits)
{
  memset(t, 0, sizeof(*t));
  t->dl_tensor.data = data;
  t->dl_tensor.device.device_type = kDLCUDA;
  t->dl_tensor.device.device_id = 0;
  t->dl_tensor.ndim = 2;
  t->dl_tensor.dtype.code = code;
  t->dl_tensor.dtype.bits = bits;
  t->dl_tensor.dtype.lanes = 1;
  t->dl_tensor.shape = shape;
  t->dl_tensor.strides = NULL;
  t->dl_tensor.byte_offset = 0;
}

static int sk_ensure_dev(sk_cuvs_index* h, void** ptr, size_t* cap, size_t need)
{
  if (*ptr != NULL && *cap >= need) { return 0; }
  if (*ptr != NULL) {
    if (cuvsRMMFree(h->res, *ptr, *cap) != CUVS_SUCCESS) { return -1; }
    *ptr = NULL;
    *cap = 0;
  }
  if (need == 0) { return 0; }
  if (cuvsRMMAlloc(h->res, ptr, need) != CUVS_SUCCESS) { return -1; }
  *cap = need;
  return 0;
}

static int sk_ensure_pinned(void** ptr, size_t* cap, size_t need)
{
  if (*ptr != NULL && *cap >= need) { return 0; }
  if (*ptr != NULL) {
    (void)cudaFreeHost(*ptr);
    *ptr = NULL;
    *cap = 0;
  }
  if (need == 0) { return 0; }
  if (cudaMallocHost(ptr, need) != cudaSuccess) { return -1; }
  *cap = need;
  return 0;
}

static int sk_handle_init(sk_cuvs_index* h)
{
  if (pthread_mutex_init(&h->exec_mu, NULL) != 0) { return -1; }
  if (pthread_mutex_init(&h->q_mu, NULL) != 0) {
    pthread_mutex_destroy(&h->exec_mu);
    return -1;
  }
  if (pthread_cond_init(&h->q_work_cv, NULL) != 0) {
    pthread_mutex_destroy(&h->q_mu);
    pthread_mutex_destroy(&h->exec_mu);
    return -1;
  }
  if (pthread_cond_init(&h->q_done_cv, NULL) != 0) {
    pthread_cond_destroy(&h->q_work_cv);
    pthread_mutex_destroy(&h->q_mu);
    pthread_mutex_destroy(&h->exec_mu);
    return -1;
  }
  return 0;
}

static int sk_ensure_workspace(sk_cuvs_index* h, long nq, long topk)
{
  size_t qbytes, out_bytes, dist_bytes;
  size_t itopk, max_itopk, width;
  long max_queries;

  if (nq <= 0 || topk <= 0 || h->dim <= 0) { return 1; }
  if (sk_mul_size((size_t)nq, (size_t)h->dim, sizeof(float), &qbytes) != 0) { return 1; }
  if (sk_mul_size((size_t)nq, (size_t)topk, sizeof(unsigned), &out_bytes) != 0) { return 1; }
  if (sk_mul_size((size_t)nq, (size_t)topk, sizeof(float), &dist_bytes) != 0) { return 1; }

  if (sk_ensure_dev(h, &h->dev_q, &h->dev_q_cap, qbytes) != 0) { return 1; }
  if (sk_ensure_dev(h, &h->dev_ids, &h->dev_ids_cap, out_bytes) != 0) { return 1; }
  if (sk_ensure_dev(h, &h->dev_dist, &h->dev_dist_cap, dist_bytes) != 0) { return 1; }
  if (sk_ensure_pinned((void**)&h->host_ids, &h->host_ids_cap, out_bytes) != 0) { return 1; }
  if (sk_ensure_pinned((void**)&h->host_dist, &h->host_dist_cap, dist_bytes) != 0) { return 1; }

  if (h->sp != NULL && h->sp_topk == (size_t)topk) { return 0; }
  if (h->sp != NULL) {
    (void)cuvsCagraSearchParamsDestroy(h->sp);
    h->sp = NULL;
  }
  if (cuvsCagraSearchParamsCreate(&h->sp) != CUVS_SUCCESS) { return 1; }

  itopk = (size_t)topk * 4;
  if (itopk < 512) { itopk = 512; }
  max_itopk = (h->n > 0) ? (size_t)h->n : itopk;
  if (max_itopk < (size_t)topk) { max_itopk = (size_t)topk; }
  if (itopk > max_itopk) { itopk = max_itopk; }
  h->sp->itopk_size = itopk;

  width = (size_t)sk_env_long("SEEKDB_CUVS_SEARCH_WIDTH", SK_DEFAULT_SEARCH_WIDTH);
  h->sp->search_width = (width == 0) ? SK_DEFAULT_SEARCH_WIDTH : width;
  max_queries = sk_env_long("SEEKDB_CUVS_MAX_QUERIES", 0);
  h->sp->max_queries = (max_queries > 0) ? (size_t)max_queries : 0;
  h->sp_topk = (size_t)topk;
  return 0;
}

static int sk_search_impl(sk_cuvs_index* h, const float* query, long nq, long topk,
                          unsigned* out_ids, float* out_dist)
{
  int64_t qshape[2], oshape[2];
  DLManagedTensor qt, nt, dt;
  cuvsFilter filter;
  size_t qbytes, out_bytes, dist_bytes;
  int rc = 0;

  if (h == NULL || query == NULL || out_ids == NULL || nq <= 0 || topk <= 0) { return 1; }
  if (h->n <= 0 || (size_t)topk > (size_t)h->n) { return 2; }
  if (sk_ensure_workspace(h, nq, topk) != 0) {
    fprintf(stderr, "[seekdb_cuvs] workspace allocation failed: %s\n", sk_err());
    return 3;
  }

  qbytes = (size_t)nq * (size_t)h->dim * sizeof(float);
  out_bytes = (size_t)nq * (size_t)topk * sizeof(unsigned);
  dist_bytes = (size_t)nq * (size_t)topk * sizeof(float);

  if (cudaMemcpy(h->dev_q, query, qbytes, cudaMemcpyDefault) != cudaSuccess) {
    rc = 4;
    goto done;
  }

  qshape[0] = nq; qshape[1] = h->dim;
  oshape[0] = nq; oshape[1] = topk;
  sk_tensor(&qt, h->dev_q, qshape, kDLFloat, 32);
  sk_tensor(&nt, h->dev_ids, oshape, kDLUInt, 32);
  sk_tensor(&dt, h->dev_dist, oshape, kDLFloat, 32);

  filter.type = NO_FILTER;
  filter.addr = (uintptr_t)0;
  if (cuvsCagraSearch(h->res, h->sp, h->idx, &qt, &nt, &dt, filter) != CUVS_SUCCESS) {
    rc = 5;
    goto done;
  }
  /* CAGRA may enqueue work on its own stream; make the D2H copy unambiguous. */
  if (cudaDeviceSynchronize() != cudaSuccess) {
    rc = 6;
    goto done;
  }
  if (cudaMemcpy(h->host_ids, h->dev_ids, out_bytes, cudaMemcpyDeviceToHost) != cudaSuccess) {
    rc = 7;
    goto done;
  }
  if (out_dist != NULL) {
    if (cudaMemcpy(h->host_dist, h->dev_dist, dist_bytes, cudaMemcpyDeviceToHost) != cudaSuccess) {
      rc = 8;
      goto done;
    }
  }
  memcpy(out_ids, h->host_ids, out_bytes);
  if (out_dist != NULL) { memcpy(out_dist, h->host_dist, dist_bytes); }

done:
  if (rc != 0) {
    fprintf(stderr, "[seekdb_cuvs] search rc=%d: %s\n", rc, sk_err());
    (void)cudaGetLastError();
  }
  return rc;
}

static void* sk_worker_main(void* arg)
{
  sk_cuvs_index* h = (sk_cuvs_index*)arg;
  for (;;) {
    const float* query;
    long nq, topk;
    unsigned* out_ids;
    float* out_dist;
    int rc;

    pthread_mutex_lock(&h->q_mu);
    while (!h->quit && !h->busy) { pthread_cond_wait(&h->q_work_cv, &h->q_mu); }
    if (h->quit) {
      pthread_mutex_unlock(&h->q_mu);
      break;
    }
    query = h->job.query;
    nq = h->job.nq;
    topk = h->job.topk;
    out_ids = h->job.out_ids;
    out_dist = h->job.out_dist;
    pthread_mutex_unlock(&h->q_mu);

    pthread_mutex_lock(&h->exec_mu);
    rc = sk_search_impl(h, query, nq, topk, out_ids, out_dist);
    pthread_mutex_unlock(&h->exec_mu);

    pthread_mutex_lock(&h->q_mu);
    h->job.rc = rc;
    h->busy = 0;
    pthread_cond_broadcast(&h->q_done_cv);
    pthread_mutex_unlock(&h->q_mu);
  }
  return NULL;
}

static int sk_start_worker(sk_cuvs_index* h)
{
  pthread_attr_t attr;
  int rc;
  if (pthread_attr_init(&attr) != 0) { return -1; }
  (void)pthread_attr_setstacksize(&attr, SK_BIG_STACK);
  rc = pthread_create(&h->worker, &attr, sk_worker_main, h);
  pthread_attr_destroy(&attr);
  if (rc != 0) {
    fprintf(stderr, "[seekdb_cuvs] warning: search worker unavailable (%s)\n", strerror(rc));
    return -1;
  }
  h->worker_started = 1;
  return 0;
}

static int sk_submit_search(sk_cuvs_index* h, const float* query, long nq, long topk,
                            unsigned* out_ids, float* out_dist)
{
  int rc;
  pthread_mutex_lock(&h->q_mu);
  while (h->busy && !h->quit) { pthread_cond_wait(&h->q_done_cv, &h->q_mu); }
  if (h->quit) {
    pthread_mutex_unlock(&h->q_mu);
    return 9;
  }
  h->job.query = query;
  h->job.nq = nq;
  h->job.topk = topk;
  h->job.out_ids = out_ids;
  h->job.out_dist = out_dist;
  h->job.rc = 0;
  h->busy = 1;
  pthread_cond_signal(&h->q_work_cv);
  while (h->busy && !h->quit) { pthread_cond_wait(&h->q_done_cv, &h->q_mu); }
  rc = h->quit ? 9 : h->job.rc;
  pthread_mutex_unlock(&h->q_mu);
  return rc;
}

struct sk_search_job {
  sk_cuvs_index* h;
  const float* query;
  long nq;
  long topk;
  unsigned* out_ids;
  float* out_dist;
  int rc;
};

static void* sk_search_thread(void* arg)
{
  struct sk_search_job* j = (struct sk_search_job*)arg;
  pthread_mutex_lock(&j->h->exec_mu);
  j->rc = sk_search_impl(j->h, j->query, j->nq, j->topk, j->out_ids, j->out_dist);
  pthread_mutex_unlock(&j->h->exec_mu);
  return NULL;
}

static int sk_search_big_stack(sk_cuvs_index* h, const float* query, long nq, long topk,
                               unsigned* out_ids, float* out_dist)
{
  struct sk_search_job job;
  pthread_t tid;
  pthread_attr_t attr;
  int rc;
  job.h = h;
  job.query = query;
  job.nq = nq;
  job.topk = topk;
  job.out_ids = out_ids;
  job.out_dist = out_dist;
  job.rc = -1;
  if (pthread_attr_init(&attr) != 0) { goto inline_call; }
  (void)pthread_attr_setstacksize(&attr, SK_BIG_STACK);
  rc = pthread_create(&tid, &attr, sk_search_thread, &job);
  pthread_attr_destroy(&attr);
  if (rc == 0) {
    pthread_join(tid, NULL);
    return job.rc;
  }
inline_call:
  pthread_mutex_lock(&h->exec_mu);
  rc = sk_search_impl(h, query, nq, topk, out_ids, out_dist);
  pthread_mutex_unlock(&h->exec_mu);
  return rc;
}

static void* sk_build_inner(const float* base, long n, long dim)
{
  sk_cuvs_index* h = NULL;
  void* dev = NULL;
  size_t bytes = 0;
  int registered = 0;
  long degree, inter, niter;
  const char* algo;
  int64_t shape[2];
  DLManagedTensor dset;
  DLManagedTensor view;
  int keep_dev = 0;

  if (base == NULL || n <= 0 || dim <= 0) { return NULL; }
  if (sk_mul_size((size_t)n, (size_t)dim, sizeof(float), &bytes) != 0) { return NULL; }

  h = (sk_cuvs_index*)calloc(1, sizeof(*h));
  if (h == NULL) { return NULL; }
  if (cuvsResourcesCreate(&h->res) != CUVS_SUCCESS) {
    fprintf(stderr, "[seekdb_cuvs] cuvsResourcesCreate failed: %s\n", sk_err());
    goto fail;
  }
  if (cuvsCagraIndexParamsCreate(&h->ip) != CUVS_SUCCESS) {
    fprintf(stderr, "[seekdb_cuvs] CagraIndexParamsCreate failed: %s\n", sk_err());
    goto fail;
  }

  degree = sk_env_long("SEEKDB_CUVS_GRAPH_DEGREE", 0);
  inter = sk_env_long("SEEKDB_CUVS_INTERMEDIATE_GRAPH_DEGREE", 0);
  niter = sk_env_long("SEEKDB_CUVS_NITER", 0);
  if (degree <= 0) { degree = SK_DEFAULT_GRAPH_DEGREE; }
  if (inter <= 0) { inter = SK_DEFAULT_INTERMEDIATE_GRAPH_DEGREE; }
  if (niter <= 0) { niter = SK_DEFAULT_NITER; }
  if (inter < degree) { inter = degree; }
  if (degree > n - 1) { degree = (n > 1) ? (n - 1) : 1; }
  if (inter > n - 1) { inter = (n > 1) ? (n - 1) : 1; }
  if (inter < degree) { inter = degree; }

  algo = getenv("SEEKDB_CUVS_BUILD_ALGO");
  if (algo != NULL && strcmp(algo, "auto") == 0) {
    h->ip->build_algo = AUTO_SELECT;
  } else if (algo != NULL && (strcmp(algo, "iterative") == 0 ||
                              strcmp(algo, "iterative_cagra_search") == 0)) {
    h->ip->build_algo = ITERATIVE_CAGRA_SEARCH;
  } else {
    h->ip->build_algo = NN_DESCENT;
  }
  h->ip->metric = L2Expanded;
  h->ip->graph_degree = (size_t)degree;
  h->ip->intermediate_graph_degree = (size_t)inter;
  h->ip->nn_descent_niter = (size_t)niter;

  if (cuvsCagraIndexCreate(&h->idx) != CUVS_SUCCESS) {
    fprintf(stderr, "[seekdb_cuvs] CagraIndexCreate failed: %s\n", sk_err());
    goto fail;
  }

  if (cuvsRMMAlloc(h->res, &dev, bytes) != CUVS_SUCCESS) {
    fprintf(stderr, "[seekdb_cuvs] device dataset alloc failed (%zu bytes): %s\n", bytes, sk_err());
    goto fail;
  }
  if (sk_env_flag("SEEKDB_CUVS_PIN_BUILD_INPUT", 1)) {
    if (cudaHostRegister((void*)base, bytes, cudaHostRegisterDefault) == cudaSuccess) {
      registered = 1;
    } else {
      (void)cudaGetLastError();
    }
  }
  if (cudaMemcpy(dev, base, bytes, cudaMemcpyHostToDevice) != cudaSuccess) {
    fprintf(stderr, "[seekdb_cuvs] dataset H2D failed: %s\n", sk_err());
    (void)cudaGetLastError();
    goto fail;
  }
  if (registered) {
    (void)cudaHostUnregister((void*)base);
    registered = 0;
  }

  shape[0] = n;
  shape[1] = dim;
  sk_tensor(&dset, dev, shape, kDLFloat, 32);
  if (cuvsCagraBuild(h->res, h->ip, &dset, h->idx) != CUVS_SUCCESS) {
    fprintf(stderr, "[seekdb_cuvs] CagraBuild failed: %s\n", sk_err());
    goto fail;
  }

  memset(&view, 0, sizeof(view));
  if (cuvsCagraIndexGetDataset(h->idx, &view) == CUVS_SUCCESS) {
    const uintptr_t d0 = (uintptr_t)dev;
    const uintptr_t d1 = d0 + bytes;
    const uintptr_t got = (uintptr_t)view.dl_tensor.data;
    if (got >= d0 && got < d1) { keep_dev = 1; }
    if (view.deleter != NULL) {
      view.deleter(&view);
    }
  } else {
    /* Conservatively keep the buffer alive if ownership cannot be determined. */
    keep_dev = 1;
    (void)cudaGetLastError();
  }

  h->n = n;
  h->dim = dim;
  if (keep_dev) {
    h->dev_dataset = dev;
    h->dev_dataset_bytes = bytes;
    h->owns_dev_dataset = 1;
    dev = NULL;
  }

  if (sk_handle_init(h) != 0) {
    fprintf(stderr, "[seekdb_cuvs] handle init failed\n");
    goto fail;
  }
  (void)sk_start_worker(h);

  if (sk_env_flag("SEEKDB_CUVS_VERBOSE", 0)) {
    fprintf(stderr,
            "[seekdb_cuvs] built n=%ld dim=%ld degree=%zu inter=%zu niter=%zu algo=%d\n",
            n, dim, h->ip->graph_degree, h->ip->intermediate_graph_degree,
            h->ip->nn_descent_niter, (int)h->ip->build_algo);
  }
  return h;

fail:
  if (registered) { (void)cudaHostUnregister((void*)base); }
  if (dev != NULL && h->res != 0) { (void)cuvsRMMFree(h->res, dev, bytes); }
  if (h->idx != NULL) { (void)cuvsCagraIndexDestroy(h->idx); }
  if (h->dev_dataset != NULL && h->res != 0) {
    (void)cuvsRMMFree(h->res, h->dev_dataset, h->dev_dataset_bytes);
  }
  if (h->ip != NULL) { (void)cuvsCagraIndexParamsDestroy(h->ip); }
  if (h->res != 0) { (void)cuvsResourcesDestroy(h->res); }
  free(h);
  return NULL;
}

struct sk_build_job {
  const float* base;
  long n;
  long dim;
  void* out;
};

static void* sk_build_thread(void* arg)
{
  struct sk_build_job* j = (struct sk_build_job*)arg;
  j->out = sk_build_inner(j->base, j->n, j->dim);
  return NULL;
}

void* seekdb_cuvs_build(const float* base, long n, long dim)
{
  struct sk_build_job job;
  pthread_t tid;
  pthread_attr_t attr;
  int rc;
  job.base = base;
  job.n = n;
  job.dim = dim;
  job.out = NULL;
  if (pthread_attr_init(&attr) != 0) { return sk_build_inner(base, n, dim); }
  (void)pthread_attr_setstacksize(&attr, SK_BIG_STACK);
  rc = pthread_create(&tid, &attr, sk_build_thread, &job);
  pthread_attr_destroy(&attr);
  if (rc == 0) {
    pthread_join(tid, NULL);
    return job.out;
  }
  return sk_build_inner(base, n, dim);
}

int seekdb_cuvs_search(void* handle, const float* query, long nq, long topk,
                       unsigned int* out_ids, float* out_dist)
{
  sk_cuvs_index* h = (sk_cuvs_index*)handle;
  if (h == NULL) { return 1; }
  if (h->worker_started) {
    return sk_submit_search(h, query, nq, topk, out_ids, out_dist);
  }
  return sk_search_big_stack(h, query, nq, topk, out_ids, out_dist);
}

void seekdb_cuvs_free(void* handle)
{
  sk_cuvs_index* h = (sk_cuvs_index*)handle;
  if (h == NULL) { return; }

  if (h->worker_started) {
    pthread_mutex_lock(&h->q_mu);
    h->quit = 1;
    pthread_cond_broadcast(&h->q_work_cv);
    pthread_cond_broadcast(&h->q_done_cv);
    pthread_mutex_unlock(&h->q_mu);
    pthread_join(h->worker, NULL);
    h->worker_started = 0;
  }

  pthread_mutex_lock(&h->exec_mu);
  if (h->sp != NULL) { (void)cuvsCagraSearchParamsDestroy(h->sp); }
  if (h->res != 0) {
    if (h->dev_q != NULL) { (void)cuvsRMMFree(h->res, h->dev_q, h->dev_q_cap); }
    if (h->dev_ids != NULL) { (void)cuvsRMMFree(h->res, h->dev_ids, h->dev_ids_cap); }
    if (h->dev_dist != NULL) { (void)cuvsRMMFree(h->res, h->dev_dist, h->dev_dist_cap); }
    if (h->owns_dev_dataset && h->dev_dataset != NULL) {
      (void)cuvsRMMFree(h->res, h->dev_dataset, h->dev_dataset_bytes);
    }
  }
  if (h->host_ids != NULL) { (void)cudaFreeHost(h->host_ids); }
  if (h->host_dist != NULL) { (void)cudaFreeHost(h->host_dist); }
  if (h->idx != NULL) { (void)cuvsCagraIndexDestroy(h->idx); }
  if (h->ip != NULL) { (void)cuvsCagraIndexParamsDestroy(h->ip); }
  if (h->res != 0) { (void)cuvsResourcesDestroy(h->res); }
  pthread_mutex_unlock(&h->exec_mu);

  pthread_mutex_destroy(&h->exec_mu);
  pthread_mutex_destroy(&h->q_mu);
  pthread_cond_destroy(&h->q_work_cv);
  pthread_cond_destroy(&h->q_done_cv);
  free(h);
}

int seekdb_cuvs_serialize(void* handle, const char* filename)
{
  sk_cuvs_index* h = (sk_cuvs_index*)handle;
  cuvsError_t err;
  if (h == NULL || filename == NULL) { return 1; }
  pthread_mutex_lock(&h->exec_mu);
  err = cuvsCagraSerialize(h->res, filename, h->idx, true);
  pthread_mutex_unlock(&h->exec_mu);
  if (err != CUVS_SUCCESS) {
    fprintf(stderr, "[seekdb_cuvs] serialize failed: %s\n", sk_err());
    return 1;
  }
  return 0;
}

void* seekdb_cuvs_deserialize(const char* filename, long n, long dim)
{
  sk_cuvs_index* h = NULL;
  if (filename == NULL || n <= 0 || dim <= 0) { return NULL; }
  h = (sk_cuvs_index*)calloc(1, sizeof(*h));
  if (h == NULL) { return NULL; }
  if (cuvsResourcesCreate(&h->res) != CUVS_SUCCESS) {
    fprintf(stderr, "[seekdb_cuvs] deserialize resources failed: %s\n", sk_err());
    goto fail;
  }
  if (cuvsCagraIndexParamsCreate(&h->ip) != CUVS_SUCCESS) {
    fprintf(stderr, "[seekdb_cuvs] deserialize params failed: %s\n", sk_err());
    goto fail;
  }
  if (cuvsCagraIndexCreate(&h->idx) != CUVS_SUCCESS) {
    fprintf(stderr, "[seekdb_cuvs] deserialize index failed: %s\n", sk_err());
    goto fail;
  }
  if (cuvsCagraDeserialize(h->res, filename, h->idx) != CUVS_SUCCESS) {
    fprintf(stderr, "[seekdb_cuvs] CagraDeserialize failed: %s\n", sk_err());
    goto fail;
  }
  {
    int64_t actual_n = 0;
    int64_t actual_dim = 0;
    if (cuvsCagraIndexGetSize(h->idx, &actual_n) != CUVS_SUCCESS ||
        cuvsCagraIndexGetDims(h->idx, &actual_dim) != CUVS_SUCCESS ||
        actual_n != n || actual_dim != dim) {
      fprintf(stderr, "[seekdb_cuvs] snapshot shape mismatch: %ld x %ld, expected %ld x %ld\n",
              (long)actual_n, (long)actual_dim, n, dim);
      goto fail;
    }
  }
  h->n = n;
  h->dim = dim;
  if (sk_handle_init(h) != 0) { goto fail; }
  (void)sk_start_worker(h);
  return h;

fail:
  if (h->idx != NULL) { (void)cuvsCagraIndexDestroy(h->idx); }
  if (h->ip != NULL) { (void)cuvsCagraIndexParamsDestroy(h->ip); }
  if (h->res != 0) { (void)cuvsResourcesDestroy(h->res); }
  free(h);
  return NULL;
}

int seekdb_cuvs_cagra_knn(const float* base, long n, long dim,
                          const float* query, long nq, long topk,
                          unsigned int* out_ids)
{
  void* h = seekdb_cuvs_build(base, n, dim);
  int rc;
  if (h == NULL) { return 10; }
  rc = seekdb_cuvs_search(h, query, nq, topk, out_ids, NULL);
  seekdb_cuvs_free(h);
  return rc;
}
