// ============================================================
// Events 状态管理 (Zustand)
// ============================================================

import { create } from 'zustand';
import { fetchEvents, fetchEventStats, type EventRecord } from '../api/events';

interface EventsState {
  events: EventRecord[];
  stats: Record<string, number>;
  isLoading: boolean;
  filterType: string;
  filterLevel: string;

  loadEvents: () => Promise<void>;
  loadStats: () => Promise<void>;
  setFilterType: (type: string) => void;
  setFilterLevel: (level: string) => void;

  /** 处理 SSE 实时事件 */
  handleSSEEvent: (event: EventRecord) => void;
}

export const useEventsStore = create<EventsState>((set, get) => ({
  events: [],
  stats: {},
  isLoading: false,
  filterType: '',
  filterLevel: '',

  loadEvents: async () => {
    set({ isLoading: true });
    try {
      const data = await fetchEvents();
      set({ events: data as EventRecord[], isLoading: false });
    } catch (e) {
      console.error('Failed to load events:', e);
      set({ isLoading: false });
    }
  },

  loadStats: async () => {
    try {
      const data = await fetchEventStats();
      set({ stats: data as unknown as Record<string, number> });
    } catch (e) {
      console.error('Failed to load event stats:', e);
    }
  },

  setFilterType: (type) => set({ filterType: type }),
  setFilterLevel: (level) => set({ filterLevel: level }),

  handleSSEEvent: (event) => {
    set((state) => ({
      events: [event, ...state.events].slice(0, 500),  // 保留最近 500 条
    }));
  },
}));
