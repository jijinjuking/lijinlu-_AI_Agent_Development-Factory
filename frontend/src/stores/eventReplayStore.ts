// ============================================================
// stores/eventReplayStore.ts — W19 Event Replay 状态管理
// ============================================================

import { create } from 'zustand';
import { fetchTaskEvents, fetchEvents, fetchEventTypes } from '../api/events';
import type {
  RuntimeEvent,
  ReplayState,
  EventQueryParams,
} from '../types/event';

interface EventReplayStore {
  // ── 事件列表（历史查询视图）──────────────────────────
  events: RuntimeEvent[];
  totalEvents: number;
  isLoadingEvents: boolean;
  eventsError: string | null;

  // ── 已知事件类型枚举 ────────────────────────────────
  eventTypes: string[];

  // ── 回放控制器状态 ──────────────────────────────────
  replay: ReplayState;

  // ── 回放定时器句柄（内部使用） ──────────────────────
  _timerId: ReturnType<typeof setTimeout> | null;

  // ──────────────────────────────────────────────────────
  // Actions
  // ──────────────────────────────────────────────────────

  /** 加载历史事件列表（分页查询） */
  loadEvents: (params?: EventQueryParams) => Promise<void>;

  /** 加载指定任务的全量事件序列（用于回放） */
  loadTaskEventsForReplay: (taskId: string) => Promise<void>;

  /** 加载所有事件类型 */
  loadEventTypes: () => Promise<void>;

  /** 开始 / 继续回放 */
  startReplay: () => void;

  /** 暂停回放 */
  pauseReplay: () => void;

  /** 停止并重置回放 */
  stopReplay: () => void;

  /** 跳到指定事件索引 */
  seekTo: (index: number) => void;

  /** 步进：前进一步 */
  stepForward: () => void;

  /** 步退：后退一步 */
  stepBackward: () => void;

  /** 设置播放速度 */
  setSpeed: (speed: number) => void;
}

const INITIAL_REPLAY: ReplayState = {
  status: 'idle',
  currentIndex: -1,
  events: [],
  speed: 1,
  activeEvent: null,
};

/** 根据速度计算每步间隔（毫秒） */
function intervalMs(speed: number): number {
  return Math.max(200, 1000 / speed);
}

export const useEventReplayStore = create<EventReplayStore>((set, get) => ({
  events: [],
  totalEvents: 0,
  isLoadingEvents: false,
  eventsError: null,
  eventTypes: [],
  replay: { ...INITIAL_REPLAY },
  _timerId: null,

  // ── 加载历史事件列表 ───────────────────────────────────
  loadEvents: async (params = {}) => {
    set({ isLoadingEvents: true, eventsError: null });
    try {
      const resp = await fetchEvents({ limit: 100, offset: 0, order: 'desc', ...params });
      set({ events: resp as RuntimeEvent[], totalEvents: resp.length, isLoadingEvents: false });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '加载事件失败';
      set({ eventsError: msg, isLoadingEvents: false });
    }
  },

  // ── 加载任务全量事件（回放序列） ─────────────────────
  loadTaskEventsForReplay: async (taskId: string) => {
    set({ isLoadingEvents: true, eventsError: null });

    // 先停掉正在进行的回放
    const { _timerId } = get();
    if (_timerId !== null) clearTimeout(_timerId);

    try {
      const resp = await fetchTaskEvents(taskId, { limit: 2000 });
      const events = (resp as any).events || (Array.isArray(resp) ? resp : []);
      set({
        isLoadingEvents: false,
        replay: {
          ...INITIAL_REPLAY,
          events,
          status: events.length > 0 ? 'idle' : 'idle',
          currentIndex: events.length > 0 ? 0 : -1,
          activeEvent: events[0] ?? null,
        },
        _timerId: null,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '加载任务事件失败';
      set({ eventsError: msg, isLoadingEvents: false });
    }
  },

  // ── 加载事件类型枚举 ───────────────────────────────────
  loadEventTypes: async () => {
    try {
      const resp = await fetchEventTypes();
      set({ eventTypes: resp.event_types });
    } catch {
      // 非关键，静默失败
    }
  },

  // ── 回放：开始 / 继续 ─────────────────────────────────
  startReplay: () => {
    const { replay, _timerId } = get();
    if (replay.events.length === 0) return;
    if (_timerId !== null) clearTimeout(_timerId);

    const advance = () => {
      const { replay: current } = get();
      if (current.status !== 'playing') return;

      const nextIndex = current.currentIndex + 1;
      if (nextIndex >= current.events.length) {
        set((s) => ({
          replay: { ...s.replay, status: 'finished', activeEvent: s.replay.events[s.replay.events.length - 1] },
          _timerId: null,
        }));
        return;
      }

      set((s) => ({
        replay: {
          ...s.replay,
          currentIndex: nextIndex,
          activeEvent: s.replay.events[nextIndex],
        },
        _timerId: setTimeout(advance, intervalMs(s.replay.speed)),
      }));
    };

    set((s) => ({
      replay: { ...s.replay, status: 'playing' },
      _timerId: setTimeout(advance, intervalMs(s.replay.speed)),
    }));
  },

  // ── 回放：暂停 ────────────────────────────────────────
  pauseReplay: () => {
    const { _timerId } = get();
    if (_timerId !== null) clearTimeout(_timerId);
    set((s) => ({
      replay: { ...s.replay, status: 'paused' },
      _timerId: null,
    }));
  },

  // ── 回放：停止并重置 ──────────────────────────────────
  stopReplay: () => {
    const { _timerId, replay } = get();
    if (_timerId !== null) clearTimeout(_timerId);
    set({
      replay: {
        ...replay,
        status: 'idle',
        currentIndex: replay.events.length > 0 ? 0 : -1,
        activeEvent: replay.events[0] ?? null,
      },
      _timerId: null,
    });
  },

  // ── 回放：跳转 ────────────────────────────────────────
  seekTo: (index: number) => {
    const { replay, _timerId } = get();
    if (_timerId !== null) clearTimeout(_timerId);
    const clampedIndex = Math.max(0, Math.min(index, replay.events.length - 1));
    set({
      replay: {
        ...replay,
        status: 'paused',
        currentIndex: clampedIndex,
        activeEvent: replay.events[clampedIndex] ?? null,
      },
      _timerId: null,
    });
  },

  // ── 回放：步进 ────────────────────────────────────────
  stepForward: () => {
    const { replay, _timerId } = get();
    if (_timerId !== null) clearTimeout(_timerId);
    const nextIndex = Math.min(replay.currentIndex + 1, replay.events.length - 1);
    set({
      replay: {
        ...replay,
        status: 'paused',
        currentIndex: nextIndex,
        activeEvent: replay.events[nextIndex] ?? null,
      },
      _timerId: null,
    });
  },

  // ── 回放：步退 ────────────────────────────────────────
  stepBackward: () => {
    const { replay, _timerId } = get();
    if (_timerId !== null) clearTimeout(_timerId);
    const prevIndex = Math.max(replay.currentIndex - 1, 0);
    set({
      replay: {
        ...replay,
        status: 'paused',
        currentIndex: prevIndex,
        activeEvent: replay.events[prevIndex] ?? null,
      },
      _timerId: null,
    });
  },

  // ── 回放：设置速度 ────────────────────────────────────
  setSpeed: (speed: number) => {
    const { _timerId, replay } = get();
    // 速度变化时若正在播放，重启定时器
    if (_timerId !== null) clearTimeout(_timerId);
    set((s) => ({ replay: { ...s.replay, speed }, _timerId: null }));
    if (replay.status === 'playing') {
      get().startReplay();
    }
  },
}));
