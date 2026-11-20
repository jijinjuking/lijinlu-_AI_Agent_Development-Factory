/**
 * K8s Scheduler API - K8s 任务调度 API 层
 * 后端 list_jobs 返回 list[dict]，clusters/nodes 也返回 list
 */
import { get, post, del } from './http';

export interface K8sJob {
  job_id: string;
  name: string;
  namespace: string;
  image: string;
  command: string[];
  resources: { cpu: string; memory: string; gpu?: string };
  status: 'pending' | 'running' | 'completed' | 'failed' | 'canceled';
  created_at: string;
  started_at?: string;
  finished_at?: string;
  node_name?: string;
  exit_code?: number;
}

export interface K8sCluster {
  cluster_id: string;
  name: string;
  namespace: string;
  status: 'healthy' | 'degraded' | 'offline';
  node_count: number;
  gpu_count: number;
  created_at: string;
}

function toArray<T>(res: unknown): T[] {
  if (!res) return [];
  if (Array.isArray(res)) return res as T[];
  return ((res as any).items ?? (res as any).jobs ?? []) as T[];
}

export async function fetchK8sJobs(params?: { namespace?: string; status?: string }): Promise<K8sJob[]> {
  const q = new URLSearchParams();
  if (params?.namespace) q.set('namespace', params.namespace);
  if (params?.status) q.set('status', params.status);
  const qs = q.toString();
  const res = await get<unknown>(`/k8s/jobs${qs ? '?' + qs : ''}`);
  return toArray<K8sJob>(res);
}

export async function fetchK8sJob(jobId: string): Promise<K8sJob> {
  return get<K8sJob>(`/k8s/jobs/${jobId}`);
}

export async function createK8sJob(data: {
  task_id: string;
  template?: string;
  capability?: string;
  env_vars?: Record<string, string>;
  config?: {
    job_name?: string;
    image?: string;
    command?: string[];
    env_vars?: Record<string, string>;
    namespace?: string;
  };
}): Promise<K8sJob> {
  return post<K8sJob>('/k8s/jobs', data);
}

export async function cancelK8sJob(jobId: string): Promise<void> {
  await post(`/k8s/jobs/${jobId}/cancel`);
}

export async function deleteK8sJob(jobId: string): Promise<void> {
  await del(`/k8s/jobs/${jobId}`);
}

export async function fetchK8sClusters(): Promise<K8sCluster[]> {
  // 后端返回 /k8s/cluster (单集群信息对象)
  const res = await get<K8sCluster | K8sCluster[] | { cluster: K8sCluster }>('/k8s/cluster');
  if (Array.isArray(res)) return res;
  if (res && (res as any).cluster) return [(res as any).cluster];
  if (res && (res as any).cluster_id) return [res as K8sCluster];
  return [];
}

export async function fetchK8sNodes(): Promise<Record<string, unknown>[]> {
  const res = await get<unknown>('/k8s/nodes');
  return toArray<Record<string, unknown>>(res);
}

// ── Store shims ────────────────────────────────────────────────────────

export const fetchJobs = fetchK8sJobs;
export const fetchClusters = fetchK8sClusters;
export const fetchJobDetail = fetchK8sJob;
export const submitJob = createK8sJob;
export const cancelJob = cancelK8sJob;
export const deleteJob = deleteK8sJob;

// ── 补充缺失的 API 函数 ──────────────────────────────────────────────

/** 获取 Job 统计信息 */
export interface K8sJobStats {
  active: number;
  completed: number;
  failed: number;
  cancelled: number;
  pending: number;
  [key: string]: number;
}
export async function fetchK8sJobStats(): Promise<K8sJobStats> {
  return get<K8sJobStats>('/k8s/jobs/stats');
}

/** 获取 Job 日志 */
export interface K8sJobLogs {
  job_id: string;
  logs: string;
  lines: number;
}
export async function fetchK8sJobLogs(
  jobId: string,
  tailLines = 100,
): Promise<K8sJobLogs> {
  return get<K8sJobLogs>(`/k8s/jobs/${jobId}/logs`, { tail_lines: tailLines } as Record<string, string | number | undefined>);
}

/** 获取 Job 模板列表 */
export async function fetchK8sTemplates(): Promise<Record<string, unknown>[]> {
  return get<Record<string, unknown>[]>('/k8s/templates');
}

/** K8s 调度器健康检查 */
export interface K8sHealth {
  status: string;
  cluster_ready: boolean;
  active_jobs: number;
  max_concurrent: number;
  nodes: number;
  ready_nodes: number;
}
export async function fetchK8sHealth(): Promise<K8sHealth> {
  return get<K8sHealth>('/k8s/health');
}

/** 批量提交 K8s Job */
export async function batchSubmitK8sJobs(data: {
  tasks: Record<string, unknown>[];
  template?: string;
  max_concurrent?: number;
}): Promise<{ submitted: number; jobs: K8sJob[] }> {
  return post<{ submitted: number; jobs: K8sJob[] }>('/k8s/jobs/batch', data);
}

/** 清理过期 K8s Job */
export async function cleanupK8sJobs(
  maxAgeHours = 24,
): Promise<{ removed: number; max_age_hours: number }> {
  return post<{ removed: number; max_age_hours: number }>(
    '/k8s/cleanup',
    { max_age_hours: maxAgeHours },
  );
}
