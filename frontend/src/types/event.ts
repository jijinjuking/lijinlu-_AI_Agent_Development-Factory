// ============================================================
// types/event.ts — W19 Event Replay 类型定义
// ============================================================

/** 事件实体（对应后端 Event ORM） */
export interface RuntimeEvent {
  id: number;
  task_id: string | null;
  event_type: string;
  event_payload: Record<string, unknown>;
  produced_at: string;
  produced_by: string | null;
}

/** 事件列表查询参数 */
export interface EventQueryParams {
  task_id?: string;
  event_type?: string;
  produced_by?: string;
  limit?: number;
  offset?: number;
  order?: 'asc' | 'desc';
}

/** 事件列表响应 */
export interface EventListResponse {
  events: RuntimeEvent[];
  total: number;
  limit: number;
  offset: number;
}

/** 任务事件序列响应 */
export interface TaskEventResponse {
  task_id: string;
  events: RuntimeEvent[];
  count: number;
}

// ──────────────────────────────────────────────────────────
// 回放状态机
// ──────────────────────────────────────────────────────────

export type ReplayStatus = 'idle' | 'playing' | 'paused' | 'finished';

/** 回放控制器状态 */
export interface ReplayState {
  status: ReplayStatus;
  /** 当前播放到的事件索引 */
  currentIndex: number;
  /** 全部事件列表 */
  events: RuntimeEvent[];
  /** 播放速度倍率 (0.5 / 1 / 2 / 4) */
  speed: number;
  /** 当前聚焦的事件 */
  activeEvent: RuntimeEvent | null;
}

// ──────────────────────────────────────────────────────────
// 事件类型颜色映射（用于时间线可视化）
// ──────────────────────────────────────────────────────────

export const EVENT_TYPE_COLOR: Record<string, string> = {
  task_created: '#1677ff',
  task_started: '#52c41a',
  task_completed: '#13c2c2',
  task_failed: '#ff4d4f',
  node_entered: '#722ed1',
  node_exited: '#eb2f96',
  tool_called: '#fa8c16',
  tool_result: '#fadb14',
  llm_called: '#a0d911',
  llm_result: '#36cfc9',
  checkpoint_saved: '#9254de',
  state_updated: '#40a9ff',
  error_occurred: '#ff4d4f',
  artifact_created: '#73d13d',
  artifact_updated: '#ffa940',
};

/** 事件记录在表格中使用的类型（与 RuntimeEvent 一致） */
export type EventRecord = RuntimeEvent;

/** 获取事件颜色，未知类型返回默认灰色 */
export function getEventColor(eventType: string): string {
  return EVENT_TYPE_COLOR[eventType] ?? '#8c8c8c';
}

/** 事件类型显示名称 */
export const EVENT_TYPE_LABEL: Record<string, string> = {
  task_created: '任务创建',
  task_started: '任务启动',
  task_completed: '任务完成',
  task_failed: '任务失败',
  node_entered: '节点进入',
  node_exited: '节点退出',
  tool_called: '工具调用',
  tool_result: '工具结果',
  llm_called: 'LLM 调用',
  llm_result: 'LLM 响应',
  checkpoint_saved: 'Checkpoint',
  state_updated: '状态更新',
  error_occurred: '错误发生',
  artifact_created: 'Artifact 创建',
  artifact_updated: 'Artifact 更新',
};

export function getEventLabel(eventType: string): string {
  return EVENT_TYPE_LABEL[eventType] ?? eventType;
}
