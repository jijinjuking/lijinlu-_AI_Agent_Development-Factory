/**
 * Performance API - 性能监控 API 层
 *
 * 后端实际路由（/api/v1/performance/*）：
 *   GET  /performance/metrics              → 实时指标对象（非数组）
 *   GET  /performance/metrics/history      → 历史指标
 *   GET  /performance/concurrency/stats    → 并发统计
 *   GET  /performance/rate-limits          → 速率限制规则列表
 *   GET  /performance/rate-limits/stats    → 速率限制统计
 *   GET  /performance/backpressure         → 背压状态
 *   GET  /performance/llm-limits           → LLM 限速
 *   GET  /performance/pool/health          → 连接池健康
 *   GET  /performance/benchmark/results    → 基准测试结果
 */
import { get, post, put, del } from './http';

export interface PerformanceMetrics {
  timestamp: string;
  total_requests: number;
  active_requests: number;
  completed_requests: number;
  failed_requests: number;
  rate_limited_requests: number;
  latency_avg: number;
  latency_p50: number;
  latency_p95: number;
  latency_p99: number;
  current_rps: number;
  avg_rps: number;
  peak_rps: number;
  error_rate: number;
  current_concurrency: number;
  peak_concurrency: number;
  llm_calls_total: number;
  llm_calls_active: number;
  llm_tokens_used: number;
  llm_429_count: number;
  cpu_percent: number;
  memory_mb: number;
  db_connections_active: number;
  db_connections_idle: number;
  sse_connections: number;
}

/** 兼容旧前端用 PerformanceSummary 的地方 */
export interface PerformanceSummary {
  period: string;
  avg_cpu_percent: number;
  avg_memory_mb: number;
  avg_response_ms: number;
  p95_response_ms: number;
  requests_per_second: number;
  error_rate_percent: number;
  token_throughput: number;
}

export interface RateLimitRule {
  rule_id: string;
  name: string;
  resource: string;
  limit: number;
  window_seconds: number;
  action: 'reject' | 'queue' | 'throttle';
  enabled: boolean;
}

export interface ConcurrencyStats {
  max_allowed: number;
  current_active: number;
  queue_length: number;
  total_admitted: number;
  total_rejected: number;
  total_completed: number;
  total_timed_out: number;
  avg_wait_time_sec: number;
  peak_concurrent: number;
  mode: string;
}

export interface BenchmarkResult {
  benchmark_id: string;
  name: string;
  status: 'running' | 'completed' | 'failed';
  started_at: string;
  duration_ms?: number;
  results?: Record<string, unknown>;
}

/** 获取实时性能指标 */
export async function fetchPerformanceMetrics(): Promise<PerformanceMetrics> {
  return get<PerformanceMetrics>('/performance/metrics');
}

/** 兼容旧接口：fetchPerformanceSummary → 映射自实时指标 */
export async function fetchPerformanceSummary(_period?: string): Promise<PerformanceSummary> {
  const m = await fetchPerformanceMetrics();
  return {
    period: _period ?? '1h',
    avg_cpu_percent: m.cpu_percent,
    avg_memory_mb: m.memory_mb,
    avg_response_ms: m.latency_avg,
    p95_response_ms: m.latency_p95,
    requests_per_second: m.current_rps,
    error_rate_percent: m.error_rate * 100,
    token_throughput: m.llm_tokens_used,
  };
}

/** 获取历史指标 */
export async function fetchMetricsHistory(params?: {
  start?: string;
  end?: string;
  interval?: string;
}): Promise<PerformanceMetrics[]> {
  const q = new URLSearchParams();
  if (params?.start) q.set('start', params.start);
  if (params?.end) q.set('end', params.end);
  if (params?.interval) q.set('interval', params.interval);
  const qs = q.toString();
  const res = await get<PerformanceMetrics[] | { items: PerformanceMetrics[] }>(`/performance/metrics/history${qs ? '?' + qs : ''}`);
  if (Array.isArray(res)) return res;
  return (res as any)?.items ?? [];
}

/** 获取并发统计 */
export async function fetchConcurrencyStats(): Promise<ConcurrencyStats> {
  return get<ConcurrencyStats>('/performance/concurrency/stats');
}

/** 获取速率限制规则 */
export async function fetchRateLimits(): Promise<RateLimitRule[]> {
  const res = await get<RateLimitRule[] | { items: RateLimitRule[] }>('/performance/rate-limits');
  if (Array.isArray(res)) return res;
  return (res as any)?.items ?? [];
}

/** 创建速率限制规则 */
export async function createRateLimit(data: Omit<RateLimitRule, 'rule_id'>): Promise<RateLimitRule> {
  return post<RateLimitRule>('/performance/rate-limits', data);
}

/** 更新速率限制规则 */
export async function updateRateLimit(ruleId: string, data: Partial<RateLimitRule>): Promise<RateLimitRule> {
  return put<RateLimitRule>(`/performance/rate-limits/${ruleId}`, data);
}

/** 删除速率限制规则 */
export async function deleteRateLimit(ruleId: string): Promise<void> {
  await del(`/performance/rate-limits/${ruleId}`);
}

/** 获取背压状态 */
export async function fetchBackpressureStatus(): Promise<Record<string, unknown>> {
  return get('/performance/backpressure');
}

/** 获取连接池健康状态 */
export async function fetchPoolHealth(): Promise<Record<string, unknown>> {
  return get('/performance/pool/health');
}

/** 获取 LLM 限速配置 */
export async function fetchLlmLimits(): Promise<Record<string, unknown>> {
  return get('/performance/llm-limits');
}

/** 获取基准测试结果 */
export async function fetchBenchmarkResults(): Promise<BenchmarkResult[]> {
  const res = await get<BenchmarkResult[] | { items: BenchmarkResult[] }>('/performance/benchmark/results');
  if (Array.isArray(res)) return res;
  return (res as any)?.items ?? [];
}

/** 运行基准测试 */
export async function runBenchmark(config?: Record<string, unknown>): Promise<{ benchmark_id: string }> {
  return post('/performance/benchmark/run', config ?? {});
}

/** 重置指标 */
export async function resetMetrics(): Promise<void> {
  await post('/performance/metrics/reset');
}

// ===== 慢查询 =====

export interface SlowQuery {
  query_id: string;
  query: string;
  avg_duration_ms: number;
  call_count: number;
  last_seen: string;
}

/** 获取慢查询列表 */
export async function fetchSlowQueries(limit?: number): Promise<SlowQuery[]> {
  const q = limit ? `?limit=${limit}` : '';
  const res = await get<SlowQuery[]>(`/performance/slow-queries${q}`);
  return Array.isArray(res) ? res : [];
}

/** 获取系统健康状态（后端 /health 端点） */
export async function fetchSystemHealth(): Promise<{
  status: 'healthy' | 'degraded' | 'unhealthy';
  checks: { name: string; status: 'pass' | 'fail' | 'warn'; detail?: string }[];
}> {
  try {
    const data = await get<Record<string, unknown>>('/health');
    return {
      status: (data.status === 'ok' ? 'healthy' : 'degraded') as 'healthy' | 'degraded',
      checks: Object.entries(data).filter(([k]) => k !== 'status').map(([k, v]) => ({
        name: k,
        status: typeof v === 'string' && v !== 'ready' ? 'warn' : 'pass',
        detail: typeof v === 'string' ? v : JSON.stringify(v),
      })),
    };
  } catch {
    return { status: 'unhealthy', checks: [] };
  }
}

// ── Store shim ─────────────────────────────────────────────────────────

export { fetchPerformanceSummary as fetchSummary };

// ── 补充缺失的 Performance API 函数 ───────────────────────

/** 获取单次基准测试结果详情 */
export async function fetchBenchmarkResult(benchmarkId: string): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>(`/performance/benchmark/results/${benchmarkId}`);
}

/** 更新并发控制配置 */
export async function updateConcurrencyConfig(data: Record<string, unknown>): Promise<Record<string, unknown>> {
  return put<Record<string, unknown>>('/performance/concurrency/config', data);
}

/** 获取限流桶统计 */
export async function fetchRateLimitStats(): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>('/performance/rate-limits/stats');
}

/** 配置 LLM 限流参数 */
export async function configureLlmLimits(data: Record<string, unknown>): Promise<Record<string, unknown>> {
  return post<Record<string, unknown>>('/performance/llm-limits/configure', data);
}

/** 重置 LLM 限流状态 */
export async function resetLlmLimits(): Promise<void> {
  await post('/performance/llm-limits/reset');
}

/** 清空背压队列 */
export async function clearBackpressure(): Promise<Record<string, unknown>> {
  return post<Record<string, unknown>>('/performance/backpressure/clear');
}

/** 更新连接池配置 */
export async function updatePoolConfig(data: Record<string, unknown>): Promise<Record<string, unknown>> {
  return post<Record<string, unknown>>('/performance/pool/config', data);
}
