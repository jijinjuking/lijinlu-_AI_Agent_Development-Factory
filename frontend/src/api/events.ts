// ============================================================
// api/events.ts — W19 Event Replay 数据请求层
// ============================================================

import { http } from './http';
import type {
  EventListResponse,
  EventQueryParams,
  EventRecord,
  RuntimeEvent,
  TaskEventResponse,
} from '../types/event';

export type { EventRecord } from '../types/event';

/** 事件统计响应 */
export interface EventStatsResponse {
  total: number;
  by_type: Record<string, number>;
  by_producer: Record<string, number>;
  recent_24h: number;
}

/** 分页查询历史事件（返回 events 数组） */
export async function fetchEvents(
  params: EventQueryParams = {},
): Promise<EventRecord[]> {
  const data = await http.get<EventListResponse>(
    '/events',
    params as Record<string, string | number | undefined>,
  );
  return data.events ?? [];
}

/** 获取单个事件详情 */
export async function fetchEvent(eventId: number): Promise<RuntimeEvent> {
  return http.get<RuntimeEvent>(`/events/${eventId}`);
}

/** 获取指定任务的完整事件序列（按时间升序，用于回放） */
export async function fetchTaskEvents(
  taskId: string,
  options?: { event_type?: string; limit?: number },
): Promise<TaskEventResponse> {
  return http.get<TaskEventResponse>(
    `/events/task/${taskId}`,
    options as Record<string, string | number | undefined>,
  );
}

/** 获取所有已知事件类型 */
export async function fetchEventTypes(): Promise<{ event_types: string[]; count: number }> {
  return http.get<{ event_types: string[]; count: number }>('/events/types');
}

/** 获取事件统计信息 */
export async function fetchEventStats(): Promise<EventStatsResponse> {
  return http.get<EventStatsResponse>('/events/stats');
}

// ── SSE 事件流 ───────────────────────────────────────

/**
 * 连接 SSE 事件流，返回 EventSource 实例。
 * 调用方自行绑定 onopen / onmessage / onerror，并在适当时机调用 es.close()。
 */
export function connectEventStream(taskId?: string): EventSource {
  let url = '/api/v1/events/stream';
  if (taskId) url += '?task_id=' + encodeURIComponent(taskId);
  return new EventSource(url);
}
