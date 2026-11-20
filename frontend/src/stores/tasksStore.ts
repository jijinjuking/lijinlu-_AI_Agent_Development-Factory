// ============================================================
// Tasks 状态管理 (Zustand)
// ============================================================

import { create } from 'zustand';
import type { Task, TaskStatus, Priority } from '../types/agent';
import {
  fetchTasks,
  createTask as apiCreateTask,
  updateTask as apiUpdateTask,
  deleteTask as apiDeleteTask,
  executeTask as apiExecuteTask,
  cancelTask as apiCancelTask,
  fetchTaskDetail,
} from '../api/tasks';

interface TasksState {
  tasks: Task[];
  currentTask: Task | null;
  isLoading: boolean;
  filterStatus: TaskStatus | 'all';
  filterPriority: Priority | 'all';

  // 列表操作
  loadTasks: () => Promise<void>;
  loadTaskDetail: (taskId: string) => Promise<void>;
  createTask: (data: Partial<Task>) => Promise<Task | null>;
  updateTask: (taskId: string, updates: Partial<Task>) => Promise<void>;
  deleteTask: (taskId: string) => Promise<void>;
  executeTask: (taskId: string) => Promise<void>;
  cancelTask: (taskId: string) => Promise<void>;

  // 筛选
  setFilterStatus: (status: TaskStatus | 'all') => void;
  setFilterPriority: (priority: Priority | 'all') => void;

  // SSE 事件处理
  handleSSEEvent: (eventType: string, data: Record<string, unknown>) => void;
}

export const useTasksStore = create<TasksState>((set, get) => ({
  tasks: [],
  currentTask: null,
  isLoading: false,
  filterStatus: 'all',
  filterPriority: 'all',

  loadTasks: async () => {
    set({ isLoading: true });
    try {
      const data = await fetchTasks();
      set({ tasks: data as unknown as Task[], isLoading: false });
    } catch (e) {
      console.error('Failed to load tasks:', e);
      set({ isLoading: false });
    }
  },

  loadTaskDetail: async (taskId: string) => {
    set({ isLoading: true });
    try {
      const data = await fetchTaskDetail(taskId);
      set({ currentTask: data as unknown as Task, isLoading: false });
    } catch (e) {
      console.error('Failed to load task detail:', e);
      set({ isLoading: false });
    }
  },

  createTask: async (data: Partial<Task>) => {
    try {
      const result = await apiCreateTask({
        name: data.title || data.name || 'New Task',
        goal_description: data.description || '',
        title: data.title || data.name || 'New Task',
        agent_id: data.agent_id || (data as any).agentId,
        priority: data.priority || 'medium',
        tags: data.tags || [],
      } as any);
      const newTask = result as unknown as Task;
      set((state) => ({ tasks: [...state.tasks, newTask] }));
      return newTask;
    } catch (e) {
      console.error('Failed to create task:', e);
      return null;
    }
  },

  updateTask: async (taskId: string, updates: Partial<Task>) => {
    try {
      await apiUpdateTask(taskId, updates);
      set((state) => ({
        tasks: state.tasks.map((t) => (t.id === taskId ? { ...t, ...updates } : t)),
        currentTask: state.currentTask?.id === taskId
          ? { ...state.currentTask, ...updates }
          : state.currentTask,
      }));
    } catch (e) {
      console.error('Failed to update task:', e);
    }
  },

  deleteTask: async (taskId: string) => {
    try {
      await apiDeleteTask(taskId);
      set((state) => ({
        tasks: state.tasks.filter((t) => t.id !== taskId),
        currentTask: state.currentTask?.id === taskId ? null : state.currentTask,
      }));
    } catch (e) {
      console.error('Failed to delete task:', e);
    }
  },

  executeTask: async (taskId: string) => {
    try {
      await apiExecuteTask(taskId);
      set((state) => ({
        tasks: state.tasks.map((t) =>
          t.id === taskId ? { ...t, status: 'running' as TaskStatus } : t
        ),
      }));
    } catch (e) {
      console.error('Failed to execute task:', e);
    }
  },

  cancelTask: async (taskId: string) => {
    try {
      await apiCancelTask(taskId);
      set((state) => ({
        tasks: state.tasks.map((t) =>
          t.id === taskId ? { ...t, status: 'cancelled' as TaskStatus } : t
        ),
      }));
    } catch (e) {
      console.error('Failed to cancel task:', e);
    }
  },

  setFilterStatus: (status) => set({ filterStatus: status }),
  setFilterPriority: (priority) => set({ filterPriority: priority }),

  handleSSEEvent: (eventType: string, data: Record<string, unknown>) => {
    const taskId = data.task_id as string;
    if (!taskId) return;

    switch (eventType) {
      case 'task_started':
        set((state) => ({
          tasks: state.tasks.map((t) =>
            t.id === taskId ? { ...t, status: 'running' as TaskStatus } : t
          ),
        }));
        break;
      case 'task_completed':
        set((state) => ({
          tasks: state.tasks.map((t) =>
            t.id === taskId ? { ...t, status: 'completed' as TaskStatus } : t
          ),
        }));
        break;
      case 'task_failed':
        set((state) => ({
          tasks: state.tasks.map((t) =>
            t.id === taskId ? { ...t, status: 'failed' as TaskStatus } : t
          ),
        }));
        break;
    }
  },
}));
