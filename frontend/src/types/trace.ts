// ============================================================
// Trace 追踪相关类型定义
// ============================================================

/** Trace 节点类型 */
export type TraceNodeType =
  | 'llm_call'
  | 'tool_call'
  | 'chain'
  | 'agent_action'
  | 'human_input'
  | 'error';

/** Trace 执行状态 */
export type TraceStatus = 'running' | 'success' | 'failed' | 'pending';

/** Trace 记录（一次完整 Agent 执行） */
export interface Trace {
  id: string;
  pipelineId: string;
  pipelineName: string;
  agentId: string;
  agentName: string;
  startTime: string;
  endTime?: string;
  duration?: number;
  status: TraceStatus;
  totalTokens: number;
  totalCost: number;
  nodeCount: number;
  errorCount: number;
  rootNodeId: string;
}

/** Trace 节点（单次 LLM 调用、工具调用等） */
export interface TraceNode {
  id: string;
  parentId: string | null;
  type: TraceNodeType;
  name: string;
  status: TraceStatus;
  startTime: string;
  endTime?: string;
  duration?: number;
  // LLM 调用特有
  model?: string;
  inputTokens?: number;
  outputTokens?: number;
  cost?: number;
  // 工具调用特有
  toolName?: string;
  // 输入输出
  input?: string;
  output?: string;
  // 错误信息
  error?: string;
  children: string[]; // 子节点 ID 列表
}

/** Trace 列表项（简略） */
export interface TraceListItem {
  id: string;
  pipelineName: string;
  agentName: string;
  status: TraceStatus;
  startTime: string;
  duration?: number;
  totalTokens: number;
  totalCost: number;
}

/** Trace 详情（含节点树） */
export interface TraceDetail extends Trace {
  nodes: TraceNode[];
  spans: TraceNode[];
}

/** Trace 节点类型映射 */
export const TRACE_NODE_TYPE_LABELS: Record<TraceNodeType, string> = {
  llm_call: 'LLM 调用',
  tool_call: '工具调用',
  chain: '流程链',
  agent_action: 'Agent 动作',
  human_input: '人工输入',
  error: '错误',
};

/** Trace 节点类型颜色 */
export const TRACE_NODE_TYPE_COLORS: Record<TraceNodeType, string> = {
  llm_call: '#1677ff',
  tool_call: '#52c41a',
  chain: '#722ed1',
  agent_action: '#fa8c16',
  human_input: '#13c2c2',
  error: '#ff4d4f',
};

/** Trace 状态标签 */
export const TRACE_STATUS_LABELS: Record<TraceStatus, string> = {
  running: '执行中',
  success: '成功',
  failed: '失败',
  pending: '等待中',
};
