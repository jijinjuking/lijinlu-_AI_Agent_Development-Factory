// ============================================================
// App 全局状态管理 (Zustand)
// ============================================================

import { create } from 'zustand';
import type { ThemeMode } from '../types/common';

interface AppState {
  theme: ThemeMode;
  sidebarCollapsed: boolean;

  toggleTheme: () => void;
  setTheme: (theme: ThemeMode) => void;
  toggleSidebar: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  theme: (localStorage.getItem('ai-os-theme') as ThemeMode) || 'dark',
  sidebarCollapsed: false,

  toggleTheme: () =>
    set((state) => {
      const next = state.theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem('ai-os-theme', next);
      return { theme: next };
    }),

  setTheme: (theme) => {
    localStorage.setItem('ai-os-theme', theme);
    set({ theme });
  },

  toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
}));
