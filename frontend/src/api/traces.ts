// ============================================================
// api/traces.ts — Traces 数据请求
// ============================================================

import { http } from './http';
import type { Trace, TraceDetail, TraceNode } from '../types/trace';

/** 列表 */
export async function fetchTraces(params?: {
  status?: string;
  agent_id?: string;
}): Promise<Trace[]> {
  return http.get<Trace[]>('/traces', params as Record<string, string | number | undefined>);
}

/** 详情 */
export async function fetchTraceDetail(traceId: string): Promise<TraceDetail> {
  return http.get<TraceDetail>(`/traces/${traceId}`);
}

/** Trace 节点列表 */
export async function fetchTraceNodes(traceId: string): Promise<TraceNode[]> {
  // 注意：API 返回的是 snake_case 格式，需要转换为 camelCase
  const rawNodes = await http.get<any[]>(`/traces/${traceId}/nodes`);
  
  // 转换 snake_case 到 camelCase
  const nodes: TraceNode[] = rawNodes.map((node: any) => ({
    id: node.id,
    parentId: node.parent_id || null,
    type: node.type,
    name: node.name,
    status: node.status,
    startTime: node.start_time || '',
    endTime: node.end_time,
    duration: node.duration || 0,
    model: node.model,
    inputTokens: node.input_tokens,
    outputTokens: node.output_tokens,
    cost: node.cost,
    toolName: node.tool_name,
    input: node.input,
    output: node.output,
    error: node.error,
    children: node.children || [],
  }));
  
  return nodes;
}
