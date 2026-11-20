// ============================================================
// Trace 追踪状态管理 (Zustand) — 真实 API
// ============================================================

import { create } from 'zustand';
import type { Trace, TraceNode, TraceListItem } from '../types/trace';
import { fetchTraces, fetchTraceDetail, fetchTraceNodes } from '../api/traces';

interface TraceState {
  traceList: TraceListItem[];
  currentTrace: Trace | null;
  traceNodes: TraceNode[];
  selectedNodeId: string | null;
  isLoading: boolean;

  loadTraceList: () => Promise<void>;
  selectTrace: (traceId: string) => Promise<void>;
  selectNode: (nodeId: string | null) => void;
  getNodeById: (nodeId: string) => TraceNode | undefined;
  getSelectedNode: () => TraceNode | undefined;
}

export const useTraceStore = create<TraceState>((set, get) => ({
  traceList: [],
  currentTrace: null,
  traceNodes: [],
  selectedNodeId: null,
  isLoading: false,

  loadTraceList: async () => {
    set({ isLoading: true });
    try {
      const data = await fetchTraces();
      const items: TraceListItem[] = data.map((t: any) => ({
        id: t.id || t.trace_id,
        pipelineName: t.pipeline_name || t.template_name || '-',
        agentName: t.agent_name || '-',
        status: t.status || 'running',
        startTime: t.start_time || t.created_at || new Date().toISOString(),
        duration: t.duration || 0,
        totalTokens: t.total_tokens || t.tokens || 0,
        totalCost: t.total_cost || t.cost || 0,
      }));
      set({ traceList: items, isLoading: false });
    } catch {
      set({ isLoading: false });
    }
  },

  selectTrace: async (traceId) => {
    set({ isLoading: true, selectedNodeId: traceId });
    try {
      // 并行获取 trace 详情和节点数据
      const [detail, nodes] = await Promise.all([
        fetchTraceDetail(traceId),
        fetchTraceNodes(traceId),
      ]);
      
      // 转换 detail 到 Trace 格式
      const currentTrace: Trace = {
        id: detail.id,
        pipelineId: detail.pipelineId || '',
        pipelineName: detail.pipelineName,
        agentId: detail.agentId || '',
        agentName: detail.agentName,
        startTime: detail.startTime,
        endTime: detail.endTime,
        duration: detail.duration,
        status: detail.status,
        totalTokens: detail.totalTokens,
        totalCost: detail.totalCost,
        nodeCount: detail.nodeCount || nodes.length,
        errorCount: detail.errorCount || 0,
        rootNodeId: detail.rootNodeId || nodes[0]?.id || '',
      };
      
      set({
        currentTrace,
        traceNodes: nodes,
        isLoading: false,
      });
    } catch (error) {
      console.error('Failed to load trace:', error);
      set({ isLoading: false });
    }
  },

  selectNode: (nodeId) => {
    set({ selectedNodeId: nodeId });
  },

  getNodeById: (nodeId) => {
    return get().traceNodes.find((n) => n.id === nodeId);
  },

  getSelectedNode: () => {
    const { traceNodes, selectedNodeId } = get();
    if (!selectedNodeId) return undefined;
    return traceNodes.find((n) => n.id === selectedNodeId);
  },
}));
