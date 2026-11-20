// ============================================================
// api/agents.ts — Agent 数据请求
// ============================================================

import { http } from './http';
import type { Agent } from '../types/agent';

export async function fetchAgents(params?: {
  status?: string;
  role?: string;
  q?: string;
}): Promise<Agent[]> {
  return http.get<Agent[]>('/agents', params as Record<string, string | number | undefined>);
}

export async function createAgent(body: Partial<Agent>): Promise<Agent> {
  return http.post<Agent>('/agents', body);
}

export async function updateAgent(id: string, body: Partial<Agent>): Promise<Agent> {
  return http.put<Agent>(`/agents/${id}`, body);
}

export async function deleteAgent(id: string): Promise<void> {
  return http.delete<void>(`/agents/${id}`);
}

/** 获取单个 Agent 详情 */
export async function fetchAgent(id: string): Promise<Agent> {
  return http.get<Agent>(`/agents/${id}`);
}

/** 更新 Agent 状态（status=running 时真正调用 LLM） */
export async function updateAgentStatus(name: string, status: string): Promise<Agent> {
  return http.post<Agent>(`/agents/${name}/status`, { status });
}
