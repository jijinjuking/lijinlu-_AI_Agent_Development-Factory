// ============================================================
// api/tools.ts — Tool Runtime API
// ============================================================

import { http } from './http';

// ── 类型定义 ──

export interface ToolInfo {
  name: string;
  display_name: string;
  description: string;
  adapter_type: string;
  permission_level: string;
  version: string;
  timeout_sec: number;
  sandbox_required: boolean;
  parameters_schema: Record<string, unknown>;
}

export interface ToolDetail extends ToolInfo {
  tags: string[];
  author: string;
  max_retries: number;
}

export interface ToolExecuteRequest {
  args: Record<string, unknown>;
  task_id?: string;
  agent_id?: string;
  permission_level?: string;
}

export interface ToolExecuteResponse {
  tool_name: string;
  status: string;
  output?: string;
  error?: string;
  exit_code?: number;
  duration_ms: number;
}

export interface AuditLogItem {
  id: string;
  tool_name: string;
  task_id: string | null;
  agent_id: string | null;
  status: string;
  input_args: Record<string, unknown>;
  output_result: string | null;
  output_error: string | null;
  duration_ms: number;
  exit_code: number | null;
  created_at: string | null;
}

export interface AuditStats {
  total: number;
  completed: number;
  failed: number;
  denied: number;
}

export interface TraceItem {
  trace_id: string;
  tool_name: string;
  input_args: Record<string, unknown>;
  task_id: string | null;
  agent_id: string | null;
  start_time: number;
  status: string;
  result: string | null;
  error: string | null;
  duration_ms: number;
}

export interface TraceStats {
  total: number;
  completed: number;
  failed: number;
  denied: number;
  running: number;
}

// ── Tool API ──

export async function listTools(params?: {
  adapter_type?: string;
  permission_level?: string;
}): Promise<ToolInfo[]> {
  return http.get<ToolInfo[]>('/tools', params);
}

export async function getTool(name: string): Promise<ToolDetail> {
  return http.get<ToolDetail>(`/tools/${name}`);
}

export async function executeTool(
  name: string,
  body: ToolExecuteRequest,
): Promise<ToolExecuteResponse> {
  return http.post<ToolExecuteResponse>(`/tools/${name}/execute`, body);
}

export async function listAuditLogs(params?: {
  limit?: number;
  tool_name?: string;
  task_id?: string;
}): Promise<{ logs: AuditLogItem[]; count: number }> {
  return http.get<{ logs: AuditLogItem[]; count: number }>('/tools/audit/list', params);
}

export async function getAuditStats(): Promise<AuditStats> {
  return http.get<AuditStats>('/tools/audit/stats');
}

export async function listTraces(params?: {
  limit?: number;
  tool_name?: string;
  task_id?: string;
}): Promise<{ traces: TraceItem[]; count: number }> {
  return http.get<{ traces: TraceItem[]; count: number }>('/tools/traces/list', params);
}

export async function getTraceStats(): Promise<TraceStats> {
  return http.get<TraceStats>('/tools/traces/stats');
}
