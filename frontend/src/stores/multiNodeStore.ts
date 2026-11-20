// ============================================================
// Multi-Node Scheduling 状态管理 (Zustand)
// ============================================================

import { create } from 'zustand';
import type { NodeInfo, NodeTask } from '../api/multiNode';
import * as multiNodeApi from '../api/multiNode';

interface MultiNodeState {
  nodes: NodeInfo[];
  tasks: NodeTask[];
  isLoading: boolean;
  selectedNodeId: string | null;

  loadNodes: () => Promise<void>;
  loadTasks: (nodeId?: string) => Promise<void>;
  registerNode: (data: Partial<NodeInfo>) => Promise<void>;
  updateNodeStatus: (nodeId: string, status: string) => Promise<void>;
  selectNode: (nodeId: string | null) => void;
}

export const useMultiNodeStore = create<MultiNodeState>((set, get) => ({
  nodes: [],
  tasks: [],
  isLoading: false,
  selectedNodeId: null,

  loadNodes: async () => {
    set({ isLoading: true });
    try {
      const data = await multiNodeApi.fetchNodes();
      set({ nodes: data as NodeInfo[], isLoading: false });
    } catch (e) {
      console.error('Failed to load nodes:', e);
      set({ isLoading: false });
    }
  },

  loadTasks: async (nodeId?) => {
    set({ isLoading: true });
    try {
      const data = await multiNodeApi.fetchTasks(nodeId);
      set({ tasks: data as NodeTask[], isLoading: false });
    } catch (e) {
      console.error('Failed to load tasks:', e);
      set({ isLoading: false });
    }
  },

  registerNode: async (data) => {
    try {
      const result = await multiNodeApi.registerNode(data as any);
      set((state) => ({ nodes: [...state.nodes, result as NodeInfo] }));
    } catch (e) {
      console.error('Failed to register node:', e);
    }
  },

  updateNodeStatus: async (nodeId, status) => {
    try {
      await multiNodeApi.updateNodeStatus(nodeId, status);
      set((state) => ({
        nodes: state.nodes.map((n) => (n.node_id === nodeId ? { ...n, status: status as NodeInfo['status'] } : n)),
      }));
    } catch (e) {
      console.error('Failed to update node status:', e);
    }
  },

  selectNode: (nodeId) => set({ selectedNodeId: nodeId }),
}));
