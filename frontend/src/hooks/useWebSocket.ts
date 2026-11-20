// ============================================================
// useWebSocket — WebSocket 双向通信 Hook
//
// 核心设计：
//   1. connIdRef 追踪当前连接，忽略旧连接的事件（StrictMode 双次 mount）
//   2. deps=[] + 延迟连接，确保只在最后一次 mount 时才真正建立连接
//   3. 直接查 localStorage，不依赖 AuthContext 时序
// ============================================================

import { useEffect, useRef, useState, useCallback } from 'react';
import type { RefObject } from 'react';

// 消息类型
export interface WSMessage {
  event: string;
  data: Record<string, unknown>;
}

// Hook 返回值
export interface UseWebSocketReturn {
  isConnected: boolean;
  lastMessage: WSMessage | null;
  sendMessage: (msg: WSMessage | Record<string, unknown>) => void;
  reconnect: () => void;
  wsRef: RefObject<WebSocket | null>;
}

interface UseWebSocketOptions {
  taskId?: string;
  onMessage?: (msg: WSMessage) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (e: Event) => void;
  reconnectInterval?: number;
  maxRetries?: number;
}

export function useWebSocket(options: UseWebSocketOptions = {}): UseWebSocketReturn {
  const {
    taskId,
    onMessage,
    onOpen,
    onClose,
    onError,
    reconnectInterval = 3000,
    maxRetries = 10,
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const connIdRef = useRef(0);
  const retriesRef = useRef(0);
  const isIntentionalClose = useRef(false);
  const isConnecting = useRef(false);
  const connectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 用 ref 包装回调，避免 effect 依赖变化
  const onMessageRef = useRef(onMessage);
  const onOpenRef = useRef(onOpen);
  const onCloseRef = useRef(onClose);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onMessageRef.current = onMessage;
    onOpenRef.current = onOpen;
    onCloseRef.current = onClose;
    onErrorRef.current = onError;
  });

  // 构建 WS URL
  const buildUrl = useCallback((): string => {
    const token = localStorage.getItem('access_token');
    if (!token) return '';
    const base = 'ws://127.0.0.1:8002/api/v1/ws';
    const params = new URLSearchParams({ token });
    if (taskId) params.set('task_id', taskId);
    return `${base}?${params.toString()}`;
  }, [taskId]);

  // 核心连接逻辑
  const connectImpl = useCallback(() => {
    if (isConnecting.current || wsRef.current?.readyState === WebSocket.OPEN) return;

    const url = buildUrl();
    if (!url) return;

    isConnecting.current = true;
    isIntentionalClose.current = false;
    const thisConnId = ++connIdRef.current;

    if (wsRef.current) {
      isIntentionalClose.current = true;
      wsRef.current.close();
      wsRef.current = null;
    }

    console.log(`[WS:${thisConnId}] Connecting...`);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (connIdRef.current !== thisConnId) return;
      console.log(`[WS:${thisConnId}] ✅ Connected`);
      setIsConnected(true);
      retriesRef.current = 0;
      isConnecting.current = false;
      onOpenRef.current?.();
    };

    ws.onmessage = (event: MessageEvent) => {
      if (connIdRef.current !== thisConnId) return;
      try {
        const msg: WSMessage = JSON.parse(event.data as string);
        setLastMessage(msg);
        onMessageRef.current?.(msg);
      } catch {
        /* ignore parse errors */
      }
    };

    ws.onclose = (event: CloseEvent) => {
      if (connIdRef.current !== thisConnId) {
        console.log(`[WS] Ignored stale conn ${thisConnId} close`);
        return;
      }
      console.log(`[WS:${thisConnId}] Disconnected: ${event.code}`);
      setIsConnected(false);
      wsRef.current = null;
      isConnecting.current = false;
      onCloseRef.current?.();

      if (!isIntentionalClose.current && retriesRef.current < maxRetries) {
        retriesRef.current += 1;
        setTimeout(connectImpl, reconnectInterval);
      }
    };

    ws.onerror = (e: Event) => {
      if (connIdRef.current !== thisConnId) return;
      console.error(`[WS:${thisConnId}] Error`);
      onErrorRef.current?.(e);
    };
  }, [buildUrl, reconnectInterval, maxRetries]);

  // 发送消息
  const sendMessage = useCallback((msg: WSMessage | Record<string, unknown>) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify(msg));
  }, []);

  // 手动重连
  const reconnect = useCallback(() => {
    retriesRef.current = 0;
    isConnecting.current = false;
    connectImpl();
  }, [connectImpl]);

  // ===== 关键：延迟连接，让 StrictMode 的第一次 mount/cleanup 先完成 =====
  useEffect(() => {
    // 清理上一次可能遗留的定时器
    if (connectTimerRef.current) {
      clearTimeout(connectTimerRef.current);
    }

    // 150ms 后再连接 —— 足够让 StrictMode 的第一次 unmount 完成
    connectTimerRef.current = setTimeout(() => {
      const token = localStorage.getItem('access_token');
      if (token) {
        connectImpl();
      }
    }, 150);

    return () => {
      isIntentionalClose.current = true;
      if (connectTimerRef.current) {
        clearTimeout(connectTimerRef.current);
        connectTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, []); // 空依赖：只在 mount / remount 时执行

  return { isConnected, lastMessage, sendMessage, reconnect, wsRef: wsRef as RefObject<WebSocket | null> };
}
