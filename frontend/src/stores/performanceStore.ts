// ============================================================
// Performance Monitoring 状态管理 (Zustand)
// ============================================================

import { create } from 'zustand';
import type { PerformanceSummary, SlowQuery } from '../api/performance';
import * as perfApi from '../api/performance';

interface PerformanceState {
  summary: PerformanceSummary | null;
  slowQueries: SlowQuery[];
  timeRange: '1h' | '24h' | '7d' | '30d';
  isLoading: boolean;

  loadSummary: () => Promise<void>;
  loadSlowQueries: () => Promise<void>;
  setTimeRange: (range: PerformanceState['timeRange']) => void;
}

export const usePerformanceStore = create<PerformanceState>((set, get) => ({
  summary: null,
  slowQueries: [],
  timeRange: '24h',
  isLoading: false,

  loadSummary: async () => {
    set({ isLoading: true });
    try {
      const data = await perfApi.fetchSummary();
      set({ summary: data as PerformanceSummary, isLoading: false });
    } catch (e) {
      console.error('Failed to load performance summary:', e);
      set({ isLoading: false });
    }
  },

  loadSlowQueries: async () => {
    try {
      const data = await perfApi.fetchSlowQueries();
      set({ slowQueries: data as SlowQuery[] });
    } catch (e) {
      console.error('Failed to load slow queries:', e);
    }
  },

  setTimeRange: (range) => set({ timeRange: range }),
}));
