// ============================================================
// api/tasks.ts — Task 数据请求（Kanban 看板后端对接）
// ============================================================

import { http } from './http';
import type { KanbanColumn, KanbanColumnType } from '../types/agent';

/** Task — 后端返回的完整任务对象 */
export interface Task {
  id: string;
  title: string;
  goal_description?: string;
  agentId?: string;
  agentName?: string;
  status: string;
  kanban_column?: string;
  priority: string;
  createdAt: string;
  updatedAt?: string;
  startedAt?: string;
  completedAt?: string;
  duration?: number;
  tokenUsage?: number;
  cost?: number;
  tags: string[];
  workflow_graph?: any;
}

/** 获取任务列表 */
export async function fetchTaskList(): Promise<Task[]> {
  return http.get<Task[]>('/tasks');
}

/** 获取单个 Task 详情 */
export async function fetchTaskDetail(id: string): Promise<Task> {
  return http.get<Task>(`/tasks/${id}`);
}

// ── 兼容旧 API ──
/** @deprecated 使用 fetchTaskList 替代 */
export async function fetchTasks(): Promise<Task[]> {
  return fetchTaskList();
}

/** 获取 Kanban 看板数据（5 列 + tasks）
 * 后端可能返回 array 或 dict，这里统一规范化为 KanbanColumn[] */
export async function fetchKanbanBoard(): Promise<KanbanColumn[]> {
  const raw = await http.get<KanbanColumn[] | Record<string, KanbanColumn>>('/tasks/kanban');

  // 如果后端返回数组，直接用
  if (Array.isArray(raw)) return raw;

  // 如果后端返回 {todo:{...}, in_progress:{...}, ...}，转为数组
  const ORDER: KanbanColumnType[] = ['todo', 'in_progress', 'review', 'done', 'failed'];
  return ORDER.map((key) => {
    const col = (raw as Record<string, KanbanColumn>)[key];
    return col ?? { id: `col-${key}`, type: key, title: key, tasks: [] };
  });
}

/** 创建 Task */
export async function createTask(body: {
  name: string;
  goal_description?: string;
  title?: string;
  agent_id?: string;
  priority?: string;
  tags?: string[];
}): Promise<any> {
  return http.post<any>('/tasks', body);
}

/** 更新 Task */
export async function updateTask(id: string, body: Partial<{
  status: string;
  kanban_column: string;
  priority: string;
  tags: string[];
  agent_id: string;
}>): Promise<any> {
  return http.put<any>(`/tasks/${id}`, body);
}

/** 删除 Task */
export async function deleteTask(id: string): Promise<void> {
  return http.delete<void>(`/tasks/${id}`);
}

/** 执行任务 */
export async function executeTask(id: string): Promise<{ status: string; task_id: string }> {
  return http.post<{ status: string; task_id: string }>(`/tasks/${id}/execute`);
}

/** 取消正在执行的任务 */
export async function cancelTask(id: string): Promise<{ status: string; task_id: string }> {
  return http.post<{ status: string; task_id: string }>(`/tasks/${id}/cancel`);
}

/** 获取当前正在运行的任务列表 */
export interface TaskExecutions {
  active_count: number;
  max_concurrent: number;
  task_ids: string[];
}
export async function fetchExecutions(): Promise<TaskExecutions> {
  return http.get<TaskExecutions>('/tasks/executions');
}
