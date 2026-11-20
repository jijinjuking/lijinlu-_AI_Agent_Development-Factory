// ============================================================
// Kanban Board 状态管理 (Zustand)
// ============================================================

import { create } from 'zustand';
import type { KanbanColumn, KanbanTask, KanbanColumnType } from '../types/agent';
import {
  fetchKanbanBoard,
  createTask as apiCreateTask,
  updateTask as apiUpdateTask,
  deleteTask as apiDeleteTask,
  executeTask as apiExecuteTask,
  cancelTask as apiCancelTask,
} from '../api/tasks';

// ── camelCase (KanbanTask) → snake_case (API body) ──
function toSnakeCase(updates: Partial<KanbanTask>): Record<string, unknown> {
  const mapping: Record<string, string> = {
    agentId: 'agent_id',
    agentName: 'agent_name',
    kanbanColumn: 'kanban_column',
    createdAt: 'created_at',
    startedAt: 'started_at',
    completedAt: 'completed_at',
    tokenUsage: 'token_usage',
  };
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(updates)) {
    const snakeKey = mapping[key] || key;
    if (value !== undefined) {
      result[snakeKey] = value;
    }
  }
  return result;
}

interface KanbanState {
  columns: KanbanColumn[];
  isLoading: boolean;

  // 操作
  loadData: () => Promise<void>;
  moveTask: (taskId: string, fromCol: KanbanColumnType, toCol: KanbanColumnType, index: number) => void;
  updateTask: (taskId: string, updates: Partial<KanbanTask>) => void;
  addTask: (task: KanbanTask, columnType: KanbanColumnType) => void;
  removeTask: (taskId: string, columnType: KanbanColumnType) => void;
  executeTask: (taskId: string) => Promise<void>;
  cancelTask: (taskId: string) => Promise<void>;

  // SSE 事件处理
  handleSSEEvent: (eventType: string, data: Record<string, unknown>) => void;
}

export const useKanbanStore = create<KanbanState>((set) => ({
  columns: [],
  isLoading: false,

  loadData: async () => {
    set({ isLoading: true });
    try {
      const data = await fetchKanbanBoard();
      set({ columns: data, isLoading: false });
    } catch (e) {
      console.error('Failed to load kanban data:', e);
      set({ isLoading: false });
    }
  },

  moveTask: (taskId, fromCol, toCol, toIndex) => {
    set((state) => {
      const newColumns = state.columns.map((col) => ({ ...col, tasks: [...col.tasks] }));
      const fromColumn = newColumns.find((c) => c.type === fromCol);
      const toColumn = newColumns.find((c) => c.type === toCol);
      if (!fromColumn || !toColumn) return state;

      const taskIndex = fromColumn.tasks.findIndex((t) => t.id === taskId);
      if (taskIndex === -1) return state;

      const [task] = fromColumn.tasks.splice(taskIndex, 1);
      const updatedTask: KanbanTask = { ...task, status: toCol };
      toColumn.tasks.splice(toIndex, 0, updatedTask);

      // 同步到后端
      apiUpdateTask(taskId, { kanban_column: toCol }).catch(console.error);

      return { columns: newColumns };
    });
  },

  updateTask: (taskId, updates) => {
    set((state) => ({
      columns: state.columns.map((col) => ({
        ...col,
        tasks: col.tasks.map((t) => (t.id === taskId ? { ...t, ...updates } : t)),
      })),
    }));
    // 转换 camelCase → snake_case 再发 API
    apiUpdateTask(taskId, toSnakeCase(updates) as Parameters<typeof apiUpdateTask>[1]).catch(console.error);
  },

  addTask: (task, columnType) => {
    // 乐观更新本地 + 异步持久化到后端
    set((state) => ({
      columns: state.columns.map((col) =>
        col.type === columnType ? { ...col, tasks: [...col.tasks, task] } : col,
      ),
    }));
    apiCreateTask({
      name: task.title,
      title: task.title,
      goal_description: '',
      agent_id: task.agentId || undefined,
      priority: task.priority,
      tags: task.tags,
    }).catch(console.error);
  },

  removeTask: (taskId, columnType) => {
    set((state) => ({
      columns: state.columns.map((col) =>
        col.type === columnType
          ? { ...col, tasks: col.tasks.filter((t) => t.id !== taskId) }
          : col,
      ),
    }));
    apiDeleteTask(taskId).catch(console.error);
  },

  executeTask: async (taskId) => {
    await apiExecuteTask(taskId);
    // 从任意列找到该任务，移到"进行中"列
    set((state) => {
      let movedTask: KanbanTask | null = null;
      const newColumns = state.columns.map((col) => {
        const idx = col.tasks.findIndex((t) => t.id === taskId);
        if (idx === -1) return { ...col, tasks: [...col.tasks] };
        const tasks = [...col.tasks];
        const [task] = tasks.splice(idx, 1);
        movedTask = { ...task, status: 'running' as any };
        return { ...col, tasks };
      });
      // 把任务插入"进行中"列
      return {
        columns: newColumns.map((col) =>
          col.type === 'in_progress' && movedTask
            ? { ...col, tasks: [movedTask, ...col.tasks] }
            : col,
        ),
      };
    });
  },

  cancelTask: async (taskId) => {
    await apiCancelTask(taskId);
    set((state) => ({
      columns: state.columns.map((col) => ({
        ...col,
        tasks: col.tasks.map((t) =>
          t.id === taskId ? { ...t, status: 'failed' as KanbanColumnType, _error: '已取消' } : t,
        ),
      })),
    }));
  },

  /** 处理 SSE 实时事件，更新看板状态 */
  handleSSEEvent: (eventType, data) => {
    const taskId = data.task_id as string;
    const taskData = data.task as KanbanTask | undefined;

    switch (eventType) {
      case 'task_started':
        if (taskData) {
          set((state) => ({
            columns: state.columns.map((col) => {
              const alreadyHas = col.tasks.some((t) => t.id === taskId);
              // 从 todo 列移除
              if (col.type === 'todo') {
                return { ...col, tasks: col.tasks.filter((t) => t.id !== taskId) };
              }
              // 已在 in_progress 则更新状态，否则追加
              if (col.type === 'in_progress') {
                if (alreadyHas) {
                  return {
                    ...col,
                    tasks: col.tasks.map((t) =>
                      t.id === taskId ? { ...t, ...taskData, status: 'running' as any } : t,
                    ),
                  };
                }
                return { ...col, tasks: [...col.tasks, { ...taskData, status: 'running' } as any] };
              }
              // 从其他列移除
              if (alreadyHas) {
                return { ...col, tasks: col.tasks.filter((t) => t.id !== taskId) };
              }
              return col;
            }),
          }));
        }
        break;

      case 'agent_thinking':
        if (taskId) {
          set((state) => ({
            columns: state.columns.map((col) => ({
              ...col,
              tasks: col.tasks.map((t) =>
                t.id === taskId
                  ? { ...t, status: 'thinking' as any, _thinking: data.message as string }
                  : t,
              ),
            })),
          }));
        }
        break;

      case 'task_completed':
        if (taskData) {
          set((state) => ({
            columns: state.columns.map((col) => ({
              ...col,
              tasks: col.type === 'in_progress'
                ? col.tasks.filter((t) => t.id !== taskId)
                : col.type === 'done'
                  ? [...col.tasks, { ...taskData, status: 'completed' } as any]
                  : col.tasks,
            })),
          }));
        }
        break;

      case 'task_failed':
        if (taskData) {
          set((state) => ({
            columns: state.columns.map((col) => ({
              ...col,
              tasks: col.type === 'in_progress'
                ? col.tasks.filter((t) => t.id !== taskId)
                : col.type === 'failed'
                  ? [...col.tasks, { ...taskData, status: 'failed', _error: data.error as string } as any]
                  : col.tasks,
            })),
          }));
        }
        break;

      case 'task_cancelled':
        if (taskData) {
          set((state) => ({
            columns: state.columns.map((col) => ({
              ...col,
              tasks: col.type === 'in_progress'
                ? col.tasks.filter((t) => t.id !== taskId)
                : col.type === 'failed'
                  ? [...col.tasks, { ...taskData, status: 'failed', _error: '任务已取消' } as any]
                  : col.tasks,
            })),
          }));
        }
        break;
    }
  },
}));
