/**
 * Issues API - Issue 跟踪 API 层
 *
 * 后端路由: /issues/ (独立路由, 不在 projects 下)
 * 后端模型字段: id, project_id, title, description, status, priority,
 *   created_by, assigned_agent_id, decomposition_strategy, task_tree_json, etc.
 */
import { get, post, del, http } from './http';

// ===== Types =====

export type IssueStatus = 'open' | 'in_progress' | 'pending_review' | 'resolved' | 'closed';
export type IssuePriority = 'critical' | 'high' | 'medium' | 'low';
export type DecompositionStrategy = 'template_match' | 'llm_generate' | 'hybrid' | 'query_expansion';

export interface Issue {
  issue_id: string;
  project_id: string;
  title: string;
  description: string;
  status: IssueStatus;
  priority: IssuePriority;
  created_by: string;
  assigned_agent_id?: string;
  assigned_agent_name?: string;
  decomposition_strategy?: DecompositionStrategy;
  task_tree?: string;           // JSON string of task tree
  task_count?: number;
  completed_task_count?: number;
  decomposed_at?: string;
  resolved_at?: string;
  created_at: string;
  updated_at: string;
  attachments?: Attachment[];
}

export interface TaskTreeNode {
  id: string;
  name: string;
  title: string;
  role: string;
  status: string;
  kanban_column?: string;
  agent_name?: string;
  children: TaskTreeNode[];
}

export interface IssueComment {
  id: string;
  issue_id: string;
  author_id: string;
  content: string;
  created_at: string;
}

export interface Comment {
  comment_id: string;
  issue_id: string;
  author_id: string;
  content: string;
  created_at: string;
}

/** 后端字段标准化 (id → issue_id) */
function normalize(i: any): Issue {
  return {
    ...i,
    issue_id: (i.issue_id ?? i.id) as string,
  } as Issue;
}

// ===== API Functions =====

/** 获取 Issue 列表 (可按 project_id, status, priority 筛选) */
export async function fetchIssues(params?: {
  project_id?: string;
  status?: IssueStatus;
  priority?: IssuePriority;
}): Promise<Issue[]> {
  const q = new URLSearchParams();
  if (params?.project_id) q.set('project_id', params.project_id);
  if (params?.status) q.set('status', params.status);
  if (params?.priority) q.set('priority', params.priority);
  const qs = q.toString();
  const res = await get<Issue[]>(`/issues/${qs ? '?' + qs : ''}`);
  const arr = Array.isArray(res) ? res : (res as Record<string, unknown>)?.items as Issue[] ?? [];
  return arr.map(normalize);
}

/** 获取单个 Issue 详情 */
export async function fetchIssue(issueId: string): Promise<Issue> {
  const res = await get<Issue>(`/issues/${issueId}`);
  return normalize(res);
}

/** 创建 Issue */
export async function createIssue(data: {
  project_id: string;
  title: string;
  description?: string;
  priority?: IssuePriority;
  assigned_agent_id?: string;
  decomposition_strategy?: DecompositionStrategy;
  created_by?: string;
}): Promise<Issue> {
  const res = await post<Issue>('/issues/', data);
  return normalize(res);
}

/** 更新 Issue */
export async function updateIssue(
  issueId: string,
  data: {
    title?: string;
    description?: string;
    status?: IssueStatus;
    priority?: IssuePriority;
    assigned_agent_id?: string;
    decomposition_strategy?: DecompositionStrategy;
  },
): Promise<Issue> {
  const res = await http.patch<Issue>(`/issues/${issueId}`, data);
  return normalize(res);
}

/** 删除 Issue */
export async function deleteIssue(issueId: string): Promise<void> {
  await del(`/issues/${issueId}`);
}

/** 分解 Issue 返回结果 */
export interface DecomposeResult {
  issue: Issue;
  taskTree: any;
}

/** 分解 Issue 为子任务树 */
export async function decomposeIssue(
  issueId: string,
  strategy: DecompositionStrategy = 'hybrid',
): Promise<DecomposeResult> {
  const res = await post<any>(`/issues/${issueId}/compose`, { strategy });
  return {
    issue: normalize(res.issue),
    taskTree: res.task_tree,
  };
}

/** 派发 Issue 子任务 */
export async function dispatchIssue(
  issueId: string,
  options?: { auto_assign?: boolean },
): Promise<{ task_count: number; assigned_count: number }> {
  return post(`/issues/${issueId}/dispatch`, options ?? { auto_assign: true });
}

/** 重新派发单个节点 */
export async function dispatchNode(issueId: string, nodeId: string): Promise<Record<string, unknown>> {
  return post(`/issues/${issueId}/dispatch/${nodeId}`);
}

/** 获取 Issue 子任务列表 */
export async function fetchIssueTasks(issueId: string): Promise<Record<string, unknown>[]> {
  const res = await get<Record<string, unknown>[]>(`/issues/${issueId}/tasks`);
  return Array.isArray(res) ? res : [];
}

/** 将扁平节点列表构建为树结构 */
function buildTaskTree(nodes: any[]): TaskTreeNode[] {
  const map = new Map<string, TaskTreeNode>();
  const roots: TaskTreeNode[] = [];

  for (const n of nodes) {
    map.set(n.id, { ...n, children: [] });
  }

  for (const n of nodes) {
    const node = map.get(n.id)!;
    if (n.parent_id && map.has(n.parent_id)) {
      map.get(n.parent_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  }

  return roots;
}

/** 获取 Issue 任务树 */
export async function fetchTaskTree(issueId: string): Promise<TaskTreeNode[]> {
  const res = await get<any>(`/issues/${issueId}/task-tree`);
  const nodes = Array.isArray(res?.nodes) ? res.nodes : [];
  return buildTaskTree(nodes);
}

/** 获取 Issue 评论 */
export async function fetchComments(issueId: string): Promise<Comment[]> {
  const res = await get<Comment[]>(`/issues/${issueId}/comments`);
  return Array.isArray(res) ? res : [];
}

/** 添加评论 */
export async function addComment(issueId: string, content: string): Promise<Comment> {
  return post<Comment>(`/issues/${issueId}/comments`, { content });
}

// ===== 附件类型 =====

export interface Attachment {
  id: string;
  issue_id: string;
  filename: string;
  file_type: string;
  file_size: number;
  created_at: string;
  download_url?: string;
}

// ===== 附件 API =====

/** 上传附件 */
export async function uploadAttachment(issueId: string, file: File): Promise<Attachment> {
  const formData = new FormData();
  formData.append('file', file);
  return http.upload<Attachment>(`/issues/${issueId}/attachments`, formData);
}

/** 获取 Issue 的所有附件 */
export async function fetchAttachments(issueId: string): Promise<Attachment[]> {
  const res = await get<Attachment[]>(`/issues/${issueId}/attachments`);
  return Array.isArray(res) ? res : [];
}

/** 删除附件 */
export async function deleteAttachment(issueId: string, attId: string): Promise<void> {
  await del(`/issues/${issueId}/attachments/${attId}`);
}

/** 获取附件下载 URL */
export function getAttachmentDownloadUrl(issueId: string, attId: string): string {
  return `/api/v1/issues/${issueId}/attachments/${attId}/download`;
}
