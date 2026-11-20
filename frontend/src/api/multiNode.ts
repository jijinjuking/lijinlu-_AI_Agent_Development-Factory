/**
 * Multi-Node Scheduler API - 多节点调度 API 层
 * 后端 list_nodes 返回 list[dict]
 */
import { get, post } from './http';

export interface NodeInfo {
  node_id: string;
  name: string;
  address: string;
  status: 'online' | 'offline' | 'draining';
  capacity: { cpu: number; memory_mb: number; gpu_count: number };
  used: { cpu: number; memory_mb: number; gpu_count: number };
  tasks_running: number;
  labels: Record<string, string>;
  last_heartbeat: string;
}

export interface NodeTask {
  task_id: string;
  node_id: string;
  status: 'assigned' | 'running' | 'completed' | 'failed';
  assigned_at: string;
  started_at?: string;
  finished_at?: string;
}

function toArray<T>(res: unknown): T[] {
  if (!res) return [];
  if (Array.isArray(res)) return res as T[];
  return ((res as any).items ?? (res as any).nodes ?? []) as T[];
}

export async function fetchNodes(): Promise<NodeInfo[]> {
  const res = await get<unknown>('/multi-node/nodes');
  return toArray<NodeInfo>(res);
}

export async function registerNode(data: {
  node_name: string;
  host: string;
  port: number;
  capabilities?: string[];
  max_tasks?: number;
  region?: string;
  zone?: string;
  weight?: number;
}): Promise<NodeInfo> {
  return post<NodeInfo>('/multi-node/nodes/register', data);
}

export async function deregisterNode(nodeId: string): Promise<void> {
  await post(`/multi-node/nodes/${nodeId}/deregister`);
}

export async function fetchNodeTasks(nodeId: string, params?: { status?: string }): Promise<NodeTask[]> {
  const q = params?.status ? `?status=${params.status}` : '';
  const res = await get<unknown>(`/multi-node/nodes/${nodeId}/tasks${q}`);
  return toArray<NodeTask>(res);
}

export async function fetchNodeTaskDistribution(): Promise<Record<string, number>> {
  return get<Record<string, number>>('/multi-node/stats');
}

export async function setNodeDraining(nodeId: string, draining: boolean): Promise<void> {
  await post(`/multi-node/nodes/${nodeId}/drain`, { draining });
}

// ── Store shims ────────────────────────────────────────────────────────

export async function fetchTasks(nodeId?: string): Promise<NodeTask[]> {
  if (!nodeId) return [];
  return fetchNodeTasks(nodeId);
}

export async function updateNodeStatus(nodeId: string, status: string): Promise<void> {
  await setNodeDraining(nodeId, status === 'draining');
}

// ── 补充缺失的 API 函数 ──────────────────────────────────────

/** 获取集群拓扑信息 */
export async function fetchClusterTopology(): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>('/multi-node/topology');
}

/** 获取单个节点详情 */
export async function fetchNode(nodeId: string): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>(`/multi-node/nodes/${nodeId}`);
}

/** 发送本节点心跳 */
export async function sendHeartbeat(): Promise<Record<string, unknown>> {
  return post<Record<string, unknown>>('/multi-node/nodes/heartbeat');
}

/** 调度单个任务到最佳节点 */
export async function scheduleTask(data: {
  task_id: string;
  capability?: string;
  workflow_payload?: Record<string, unknown>;
  strategy?: string;
  region?: string;
}): Promise<{ task_id: string; routing: Record<string, unknown> }> {
  return post<{ task_id: string; routing: Record<string, unknown> }>('/multi-node/schedule', data);
}

/** 批量调度任务 */
export async function scheduleBatch(data: {
  tasks: Record<string, unknown>[];
  capability?: string;
  strategy?: string;
}): Promise<{ total: number; dispatched: number; failed: number; results: Record<string, unknown>[] }> {
  return post<{ total: number; dispatched: number; failed: number; results: Record<string, unknown>[] }>('/multi-node/schedule/batch', data);
}

/** 标记远程任务完成 */
export async function completeTask(taskId: string, result?: Record<string, unknown>): Promise<{ task_id: string; status: string }> {
  return post<{ task_id: string; status: string }>(`/multi-node/tasks/${taskId}/complete`, result ?? {});
}

/** 多节点调度器健康检查 */
export async function fetchMultiNodeHealth(): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>('/multi-node/health');
}
