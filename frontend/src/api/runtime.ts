/**
 * Runtime Ops API - 运行时运维 API 层
 * 覆盖 Scheduler / ModelRouter / Sandbox / LoopDetector / PolicyEngine
 */
import { get, post, put, del } from './http';

// ===== Types =====

export interface WorkerInfo {
  worker_id: string;
  name: string;
  capabilities: string[];
  current_load: number;
  max_load: number;
  status: 'active' | 'draining' | 'offline';
  last_heartbeat: string;
  registered_at: string;
}

export interface SchedulerQueueStatus {
  queue_length: number;
  running: number;
  pending: number;
  workers_total: number;
  workers_active: number;
}

export interface SchedulerConfig {
  max_retries: number;
  default_timeout: number;
  enable_preemption: boolean;
  queue_concurrency: number;
}

export interface ModelInfo {
  model_id: string;
  name: string;
  provider: string;
  context_window: number;
  input_price: number;
  output_price: number;
  tags: string[];
  enabled: boolean;
}

export interface ModelRouterConfig {
  default_model: string;
  fallback_models: string[];
  cost_aware: boolean;
  latency_aware: boolean;
}

export interface SandboxInfo {
  sandbox_id: string;
  sandbox_type: 'docker' | 'browser' | 'python';
  status: 'creating' | 'ready' | 'running' | 'destroyed' | 'error';
  created_at: string;
  destroyed_at?: string;
  metadata?: Record<string, unknown>;
}

export interface LoopDetectorStatus {
  task_id: string;
  is_looping: boolean;
  iteration_count: number;
  max_iterations: number;
  loop_type?: 'single_node' | 'sequence' | 'total';
  auto_recovery?: boolean;
}

export interface PolicyRule {
  rule_id: string;
  name: string;
  description: string;
  resource: string;
  action: string;
  effect: 'allow' | 'deny' | 'conditional';
  priority: number;
  enabled: boolean;
}

export interface AuditLogEntry {
  log_id: string;
  timestamp: string;
  task_id: string;
  action: string;
  resource: string;
  decision: 'allow' | 'deny';
  reason?: string;
  metadata?: Record<string, unknown>;
}

// ===== Scheduler =====

export async function fetchWorkers(): Promise<WorkerInfo[]> {
  const res = await get<WorkerInfo[] | { workers: WorkerInfo[] }>('/runtime/scheduler/workers');
  if (Array.isArray(res)) return res;
  return (res as any)?.workers ?? [];
}

export async function registerWorker(data: {
  name: string;
  capabilities: string[];
  max_load?: number;
}): Promise<WorkerInfo> {
  const res = await post<WorkerInfo>('/runtime/scheduler/workers', data);
  return res;
}

export async function deregisterWorker(workerId: string): Promise<void> {
  await del(`/runtime/scheduler/workers/${workerId}`);
}

export async function fetchSchedulerStatus(): Promise<SchedulerQueueStatus> {
  const res = await get<SchedulerQueueStatus>('/runtime/scheduler/status');
  return res;
}

export async function fetchSchedulerConfig(): Promise<SchedulerConfig> {
  const res = await get<SchedulerConfig>('/runtime/scheduler/config');
  return res;
}

export async function updateSchedulerConfig(data: Partial<SchedulerConfig>): Promise<SchedulerConfig> {
  const res = await put<SchedulerConfig>('/runtime/scheduler/config', data);
  return res;
}

export async function pauseScheduler(): Promise<void> {
  await post('/runtime/scheduler/pause');
}

export async function resumeScheduler(): Promise<void> {
  await post('/runtime/scheduler/resume');
}

// ===== Model Router =====

export async function fetchModels(): Promise<ModelInfo[]> {
  // 后端: GET /api/v1/runtime/models → { models: [...], count: N }
  const res = await get<ModelInfo[] | { models: ModelInfo[]; count?: number }>('/runtime/models');
  if (Array.isArray(res)) return res;
  return (res as any)?.models ?? [];
}

export async function fetchModelRouterConfig(): Promise<ModelRouterConfig> {
  const res = await get<ModelRouterConfig>('/runtime/model-router/config');
  return res;
}

export async function updateModelRouterConfig(data: Partial<ModelRouterConfig>): Promise<ModelRouterConfig> {
  const res = await put<ModelRouterConfig>('/runtime/model-router/config', data);
  return res;
}

export async function enableModel(modelId: string): Promise<void> {
  await post(`/runtime/model-router/models/${modelId}/enable`);
}

export async function disableModel(modelId: string): Promise<void> {
  await post(`/runtime/model-router/models/${modelId}/disable`);
}

// ===== Sandbox =====

export async function fetchSandboxes(): Promise<SandboxInfo[]> {
  const res = await get<SandboxInfo[] | { sandboxes: SandboxInfo[]; total?: number }>('/runtime/sandbox/list');
  if (Array.isArray(res)) return res;
  return (res as any)?.sandboxes ?? [];
}

export async function createSandbox(data: {
  sandbox_type: 'docker' | 'browser' | 'python';
  config?: Record<string, unknown>;
}): Promise<SandboxInfo> {
  const res = await post<SandboxInfo>('/runtime/sandbox/create', data);
  return res;
}

export async function destroySandbox(sandboxId: string): Promise<void> {
  await del(`/runtime/sandbox/${sandboxId}`);
}

export async function destroyAllSandboxes(): Promise<void> {
  await post('/runtime/sandbox/destroy-all');
}

// ===== Loop Detector =====

export async function fetchLoopStatus(taskId: string): Promise<LoopDetectorStatus> {
  const res = await get<LoopDetectorStatus>(`/runtime/loop-detector/${taskId}`);
  return res;
}

export async function fetchAllLoopStatuses(): Promise<LoopDetectorStatus[]> {
  const res = await get<LoopDetectorStatus[] | { statuses: LoopDetectorStatus[] }>('/runtime/loop-detector/status');
  if (Array.isArray(res)) return res;
  return (res as any)?.statuses ?? [];
}

export async function resetLoop(taskId: string): Promise<void> {
  await post(`/runtime/loop-detector/${taskId}/reset`);
}

export async function setLoopMaxIterations(taskId: string, maxIter: number): Promise<void> {
  await put(`/runtime/loop-detector/${taskId}/max-iterations`, { max_iterations: maxIter });
}

// ===== Policy Engine =====

export async function fetchPolicyRules(): Promise<PolicyRule[]> {
  const res = await get<PolicyRule[] | { rules: PolicyRule[] }>('/runtime/policy/rules');
  if (Array.isArray(res)) return res;
  return (res as any)?.rules ?? [];
}

export async function createPolicyRule(data: Omit<PolicyRule, 'rule_id'>): Promise<PolicyRule> {
  const res = await post<PolicyRule>('/runtime/policy/rules', data);
  return res;
}

export async function updatePolicyRule(ruleId: string, data: Partial<PolicyRule>): Promise<PolicyRule> {
  const res = await put<PolicyRule>(`/runtime/policy/rules/${ruleId}`, data);
  return res;
}

export async function deletePolicyRule(ruleId: string): Promise<void> {
  await del(`/runtime/policy/rules/${ruleId}`);
}

export async function fetchAuditLogs(params?: {
  task_id?: string;
  limit?: number;
  offset?: number;
}): Promise<AuditLogEntry[]> {
  const query = new URLSearchParams();
  if (params?.task_id) query.set('task_id', params.task_id);
  if (params?.limit) query.set('limit', String(params.limit));
  if (params?.offset) query.set('offset', String(params.offset));
  const qs = query.toString();
  // 后端: GET /api/v1/runtime/policy/audit → { logs: [...], count: N }
  const res = await get<AuditLogEntry[] | { logs: AuditLogEntry[] }>(`/runtime/policy/audit${qs ? '?' + qs : ''}`);
  if (Array.isArray(res)) return res;
  return (res as any)?.logs ?? [];
}

export async function fetchPolicyConfig(): Promise<Record<string, unknown>> {
  const res = await get<Record<string, unknown>>('/runtime/policy/config');
  return res;
}

export async function updatePolicyConfig(data: Record<string, unknown>): Promise<Record<string, unknown>> {
  const res = await put<Record<string, unknown>>('/runtime/policy/config', data);
  return res;
}

// ── 补充缺失的 Runtime API 函数 ───────────────────────────

/** Scheduler ping */
export async function fetchSchedulerPing(): Promise<{ pong: boolean }> {
  return get<{ pong: boolean }>('/runtime/scheduler/ping');
}

/** Scheduler 统计信息 */
export async function fetchSchedulerStats(): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>('/runtime/scheduler/stats');
}

/** Scheduler 队列详情 */
export async function fetchSchedulerQueue(limit = 20): Promise<{ queue_size: number; items: Record<string, unknown>[] }> {
  return get<{ queue_size: number; items: Record<string, unknown>[] }>('/runtime/scheduler/queue', { limit });
}

/** 模型路由决策（不实际执行） */
export async function fetchModelRoute(params?: {
  task_type?: string;
  complexity?: string;
  strategy?: string;
}): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>('/runtime/models/route', params as Record<string, string | number | undefined>);
}

/** Sandbox 统计信息 */
export async function fetchSandboxStats(): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>('/runtime/sandbox/stats');
}

/** 可用 Sandbox 类型列表 */
export async function fetchSandboxTypes(): Promise<{ types: string[] }> {
  return get<{ types: string[] }>('/runtime/sandbox/types');
}

/** Loop Detector 统计信息 */
export async function fetchLoopDetectorStats(taskId?: string): Promise<Record<string, unknown>> {
  const p = taskId ? { task_id: taskId } : {};
  return get<Record<string, unknown>>('/runtime/loop-detector/stats', p as Record<string, string | number | undefined>);
}

/** Loop Detector 配置 */
export async function fetchLoopDetectorConfig(): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>('/runtime/loop-detector/config');
}

/** Token 预算使用情况 */
export async function fetchPolicyBudget(projectId = 'default'): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>('/runtime/policy/budget', { project_id: projectId });
}

/** 成本控制状态 */
export async function fetchPolicyCost(projectId = 'default'): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>('/runtime/policy/cost', { project_id: projectId });
}

/** 策略引擎总览统计 */
export async function fetchPolicyStats(): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>('/runtime/policy/stats');
}
