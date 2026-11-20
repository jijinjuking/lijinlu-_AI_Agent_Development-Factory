/**
 * Projects API - 项目管理 API 层
 *
 * 后端字段映射：
 *   Project.id  → project_id（后端用 id，前端适配为 project_id）
 *   Issue.id    → issue_id
 *   Issues 路由：GET/POST /issues/（不嵌套在 projects 下，用 project_id 做 query param 过滤）
 */
import { get, post, del } from './http';

export type IssueStatus = 'open' | 'in_progress' | 'review' | 'done' | 'closed';
export type IssuePriority = 'critical' | 'high' | 'medium' | 'low';
export type IssueType = 'bug' | 'feature' | 'task' | 'epic';

export interface Project {
  project_id: string;   // 前端统一用 project_id（映射自后端 id）
  id?: string;          // 后端原始字段，保留兼容
  name: string;
  description?: string;
  status: 'active' | 'archived';
  owner_id?: string;    // 后端叫 created_by
  created_by?: string;
  member_ids?: string[];
  created_at: string;
  updated_at: string;
  tags?: string[];
}

export interface Issue {
  issue_id: string;     // 前端统一用 issue_id（映射自后端 id）
  id?: string;
  project_id: string;
  title: string;
  description?: string;
  status: IssueStatus;
  priority: IssuePriority;
  type?: IssueType;
  assignee_id?: string;
  assigned_agent_id?: string;
  assigned_agent_name?: string;
  creator_id?: string;
  created_by?: string;
  labels?: string[];
  task_count?: number;
  completed_task_count?: number;
  created_at: string;
  updated_at: string;
  closed_at?: string;
  decomposition_strategy?: string;
  task_tree?: string;
}

export interface Comment {
  comment_id: string;
  issue_id: string;
  author_id: string;
  content: string;
  created_at: string;
}

/** 后端 Project 字段标准化（id → project_id） */
function normalizeProject(p: any): Project {
  return {
    ...p,
    project_id: (p.project_id ?? p.id) as string,
  } as Project;
}

/** 后端 Issue 字段标准化（id → issue_id） */
function normalizeIssue(i: any): Issue {
  return {
    ...i,
    issue_id: (i.issue_id ?? i.id) as string,
  } as Issue;
}

// ===== Projects =====

export async function fetchProjects(params?: {
  status?: 'active' | 'archived';
  member_id?: string;
}): Promise<Project[]> {
  const q = new URLSearchParams();
  if (params?.status) q.set('status', params.status);
  if (params?.member_id) q.set('member_id', params.member_id);
  const qs = q.toString();
  // 后端路由 GET /api/v1/projects/ 直接返回数组
  const res = await get<Project[]>(`/projects/${qs ? '?' + qs : ''}`);
  const arr = Array.isArray(res) ? res : (res as any)?.items ?? [];
  return arr.map(normalizeProject);
}

export async function fetchProject(projectId: string): Promise<Project> {
  const res = await get<Project>(`/projects/${projectId}`);
  return normalizeProject(res);
}

export async function createProject(data: {
  name: string;
  description?: string;
  tags?: string[];
}): Promise<Project> {
  const res = await post<Project>('/projects/', data);
  return normalizeProject(res);
}

export async function updateProject(projectId: string, data: Partial<Project>): Promise<Project> {
  // 后端用 PATCH
  const res = await fetch(`/api/v1/projects/${projectId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  const json = await res.json();
  return normalizeProject(json);
}

export async function deleteProject(projectId: string): Promise<void> {
  await del(`/projects/${projectId}`);
}

// ===== Issues =====

export async function fetchIssues(projectId: string, params?: {
  status?: IssueStatus;
  assignee_id?: string;
  labels?: string[];
}): Promise<Issue[]> {
  const q = new URLSearchParams();
  // 后端 issues 不嵌套在 projects 下，用 project_id query param 过滤
  q.set('project_id', projectId);
  if (params?.status) q.set('status', params.status);
  if (params?.assignee_id) q.set('assignee_id', params.assignee_id);
  if (params?.labels?.length) q.set('labels', params.labels.join(','));
  const res = await get<Issue[]>(`/issues/?${q.toString()}`);
  const arr = Array.isArray(res) ? res : (res as any)?.items ?? [];
  return arr.map(normalizeIssue);
}

export async function fetchIssue(issueId: string): Promise<Issue> {
  const res = await get<Issue>(`/issues/${issueId}`);
  return normalizeIssue(res);
}

export async function createIssue(_projectId: string, data: {
  title: string;
  description?: string;
  priority?: IssuePriority;
  type?: IssueType;
  assignee_id?: string;
  labels?: string[];
  project_id?: string;
}): Promise<Issue> {
  // 后端 POST /issues/ 直接创建，需要带 project_id
  const payload = { ...data, project_id: _projectId };
  const res = await post<Issue>('/issues/', payload);
  return normalizeIssue(res);
}

export async function updateIssue(issueId: string, data: Partial<Issue>): Promise<Issue> {
  const res = await fetch(`/api/v1/issues/${issueId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  const json = await res.json();
  return normalizeIssue(json);
}

export async function deleteIssue(issueId: string): Promise<void> {
  await del(`/issues/${issueId}`);
}

export async function decomposeIssue(issueId: string): Promise<Issue> {
  const res = await post<Issue>(`/issues/${issueId}/decompose`);
  return normalizeIssue(res);
}

// ===== Comments =====

export async function fetchComments(issueId: string): Promise<Comment[]> {
  const res = await get<Comment[]>(`/issues/${issueId}/comments`);
  return Array.isArray(res) ? res : [];
}

export async function createComment(issueId: string, content: string): Promise<Comment> {
  return post<Comment>(`/issues/${issueId}/comments`, { content });
}
