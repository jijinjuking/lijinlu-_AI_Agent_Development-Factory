// ============================================================
// useSSE — Server-Sent Events 订阅 Hook
// ============================================================

import { useEffect, useRef, useCallback } from 'react';

export type SSEEventType =
  | 'connected'
  | 'task_started'
  | 'agent_thinking'
  | 'token_usage'
  | 'task_completed'
  | 'task_failed'
  | 'kanban_update';

export interface SSEEvent {
  event: SSEEventType;
  data: Record<string, unknown>;
}

type SSEHandler = (event: SSEEvent) => void;

const BASE = '/api/v1';

/**
 * 订阅 SSE 事件流
 * @param taskId 可选，按任务过滤
 * @param onEvent 事件回调
 */
export function useSSE(taskId: string | null, onEvent: SSEHandler) {
  const esRef = useRef<EventSource | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const connect = useCallback(() => {
    const url = taskId
      ? `${BASE}/events/stream?task_id=${taskId}`
      : `${BASE}/events/stream`;

    const es = new EventSource(url);
    esRef.current = es;

    es.onmessage = (msg) => {
      try {
        const parsed: SSEEvent = JSON.parse(msg.data);
        onEventRef.current(parsed);
      } catch {
        // 忽略解析失败（心跳等）
      }
    };

    es.onerror = () => {
      // 连接断开后 3 秒重连
      es.close();
      setTimeout(connect, 3000);
    };
  }, [taskId]);

  useEffect(() => {
    connect();
    return () => {
      esRef.current?.close();
    };
  }, [connect]);
}
