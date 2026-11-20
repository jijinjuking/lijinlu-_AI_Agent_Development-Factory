// ============================================================
// Agent 相关类型定义
// ============================================================

/** Agent 运行状态 */
export type AgentStatus =
  | 'idle'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'waiting';

/** Agent 角色类型 */
export type AgentRole =
  | 'architect'
  | 'developer'
  | 'reviewer'
  | 'tester'
  | 'deployer'
  | 'custom';

/** Agent 定义 */
export interface Agent {
  id: string;
  name: string;
  role: AgentRole;
  status: AgentStatus;
  model: string;
  model_mode: string;  // 'bound' | 'auto'
  description: string;
  system_prompt: string | null;  // 自定义系统提示词，null 则用角色默认
  capability_tags: string;
  createdAt: string;
  lastActiveAt: string;
  totalTasks: number;
  completedTasks: number;
  failedTasks: number;
  avgDuration: number; // ms
  totalTokens: number;
  totalCost: number; // ¥
  is_active: boolean;
}

/** Kanban 列状态 */
export type KanbanColumnType = 'todo' | 'in_progress' | 'review' | 'done' | 'failed';

/** Kanban 列 */
export interface KanbanColumn {
  id: string;
  type: KanbanColumnType;
  title: string;
  tasks: KanbanTask[];
}

/** Agent 看板任务 */
export interface KanbanTask {
  id: string;
  title: string;
  agentId: string | null;  // 可为空（任务未分配 Agent）
  agentName: string;
  status: KanbanColumnType;
  priority: 'low' | 'medium' | 'high' | 'critical';
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  duration?: number;
  tokenUsage?: number;
  cost?: number;
  tags: string[];
}

/** Kanban 列类型映射 */
export const KANBAN_COLUMNS: { type: KanbanColumnType; title: string }[] = [
  { type: 'todo', title: '待办' },
  { type: 'in_progress', title: '进行中' },
  { type: 'review', title: '审查中' },
  { type: 'done', title: '已完成' },
  { type: 'failed', title: '已失败' },
];

/** Agent 角色映射 */
export const AGENT_ROLE_LABELS: Record<AgentRole, string> = {
  architect: '架构师',
  developer: '开发者',
  reviewer: '审查员',
  tester: '测试员',
  deployer: '部署员',
  custom: '自定义',
};

/** Agent 角色颜色映射 */
export const AGENT_ROLE_COLORS: Record<AgentRole, string> = {
  architect: '#722ed1',
  developer: '#1677ff',
  reviewer: '#fa8c16',
  tester: '#52c41a',
  deployer: '#13c2c2',
  custom: '#8c8c8c',
};

/** Agent 状态映射 */
export const AGENT_STATUS_LABELS: Record<AgentStatus, string> = {
  idle: '空闲',
  running: '运行中',
  paused: '已暂停',
  completed: '已完成',
  failed: '已失败',
  waiting: '等待中',
};

// ── Task types (shared with tasksStore) ──────────────────────────────

export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export type Priority = 'low' | 'medium' | 'high' | 'critical';

export interface Task {
  id: string;
  name: string;
  title: string;
  description: string;
  status: TaskStatus;
  priority: Priority;
  agent_id?: string;
  project_id?: string;
  created_at: string;
  updated_at: string;
  tags: string[];
}
