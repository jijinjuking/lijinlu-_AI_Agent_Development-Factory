// ============================================================
// Evaluation 状态管理 (Zustand)
// ============================================================

import { create } from 'zustand';
import type { EvaluationRecord, Dataset, EvaluationMetrics, EvaluationComparison } from '../api/evaluation';
import * as evalApi from '../api/evaluation';

interface EvaluationState {
  records: EvaluationRecord[];
  datasets: Dataset[];
  metrics: EvaluationMetrics[];
  comparisons: EvaluationComparison[];
  currentRecord: EvaluationRecord | null;
  isLoading: boolean;
  activeTab: string;

  loadAll: () => Promise<void>;
  loadRecords: () => Promise<void>;
  loadDatasets: () => Promise<void>;
  loadMetrics: (taskIds: string[]) => Promise<void>;
  loadComparisons: (taskIds: string[]) => Promise<void>;
  selectRecord: (recordId: string) => Promise<void>;
  createDataset: (data: Partial<Dataset>) => Promise<void>;
  deleteDataset: (datasetId: string) => Promise<void>;
  triggerEvaluation: (data: { task_id: string; dataset_id?: string }) => Promise<void>;
  setActiveTab: (tab: string) => void;
}

export const useEvaluationStore = create<EvaluationState>((set, get) => ({
  records: [],
  datasets: [],
  metrics: [],
  comparisons: [],
  currentRecord: null,
  isLoading: false,
  activeTab: 'records',

  loadAll: async () => {
    set({ isLoading: true });
    try {
      const [records, datasets] = await Promise.all([
        evalApi.fetchRecords().catch(() => []),
        evalApi.fetchDatasets().catch(() => []),
      ]);
      set({ records, datasets, isLoading: false });
    } catch (e) {
      console.error('Failed to load evaluation data:', e);
      set({ isLoading: false });
    }
  },

  loadRecords: async () => {
    try {
      const records = await evalApi.fetchRecords();
      set({ records });
    } catch (e) {
      console.error('Failed to load records:', e);
    }
  },

  loadDatasets: async () => {
    try {
      const datasets = await evalApi.fetchDatasets();
      set({ datasets });
    } catch (e) {
      console.error('Failed to load datasets:', e);
    }
  },

  loadMetrics: async (taskIds) => {
    try {
      const metrics = await evalApi.fetchMetrics();
      set({ metrics: metrics as any });
    } catch (e) {
      console.error('Failed to load metrics:', e);
    }
  },

  loadComparisons: async (taskIds) => {
    try {
      const comparisons = await evalApi.fetchComparison(taskIds);
      set({ comparisons: comparisons as any });
    } catch (e) {
      console.error('Failed to load comparisons:', e);
    }
  },

  selectRecord: async (recordId) => {
    try {
      const record = await evalApi.fetchRecordDetail(recordId);
      set({ currentRecord: record });
    } catch (e) {
      console.error('Failed to load record detail:', e);
    }
  },

  createDataset: async (data) => {
    try {
      await evalApi.createDataset(data as any);
      await get().loadDatasets();
    } catch (e) {
      console.error('Failed to create dataset:', e);
    }
  },

  deleteDataset: async (datasetId) => {
    try {
      await evalApi.deleteDataset(datasetId);
      await get().loadDatasets();
    } catch (e) {
      console.error('Failed to delete dataset:', e);
    }
  },

  triggerEvaluation: async (data) => {
    try {
      await evalApi.triggerEvaluation(data as any);
      await get().loadRecords();
    } catch (e) {
      console.error('Failed to trigger evaluation:', e);
    }
  },

  setActiveTab: (tab) => set({ activeTab: tab }),
}));
