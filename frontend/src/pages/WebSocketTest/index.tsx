// ============================================================
// WebSocket 功能测试组件
// 测试 useWebSocket Hook 的所有功能
// ============================================================

import React, { useState, useEffect } from 'react';
import { useWebSocket } from '../../hooks/useWebSocket';

export default function WebSocketTest() {
  const [logs, setLogs] = useState<string[]>([]);
  const [subscribeTaskId, setSubscribeTaskId] = useState('');

  // WebSocket Hook
  const {
    isConnected,
    lastMessage,
    sendMessage,
    reconnect,
  } = useWebSocket({
    onMessage: (msg) => {
      addLog(`📨 收到消息: ${JSON.stringify(msg)}`, 'info');
    },
    onOpen: () => {
      addLog('✅ WebSocket 连接成功！', 'success');
    },
    onClose: () => {
      addLog('❌ WebSocket 连接关闭', 'error');
    },
    onError: (e) => {
      addLog(`❌ WebSocket 错误: ${e.type}`, 'error');
    },
  });

  // 添加日志
  const addLog = (msg: string, cls: string = 'info') => {
    setLogs(prev => [...prev.slice(-50), `[${new Date().toLocaleTimeString()}] ${msg}`]);
  };

  // 监听 lastMessage
  useEffect(() => {
    if (lastMessage) {
      addLog(`📨 lastMessage 更新: ${JSON.stringify(lastMessage)}`, 'info');
    }
  }, [lastMessage]);

  // 发送 Ping
  const handleSendPing = () => {
    sendMessage({ type: 'ping', timestamp: Date.now() });
    addLog('📤 已发送 Ping', 'info');
  };

  // 订阅任务
  const handleSubscribe = () => {
    if (!subscribeTaskId) {
      addLog('⚠️ 请输入 task_id', 'error');
      return;
    }
    sendMessage({ type: 'subscribe', task_id: subscribeTaskId });
    addLog(`📤 已订阅任务: ${subscribeTaskId}`, 'info');
  };

  // 手动重连
  const handleReconnect = () => {
    reconnect();
    addLog('🔄 手动重连...', 'info');
  };

  return (
    <div style={{ padding: 20, fontFamily: 'monospace' }}>
      <h2>WebSocket 功能测试</h2>

      {/* 连接状态 */}
      <div style={{ marginBottom: 20, padding: 10, background: isConnected ? '#1a3a1a' : '#3a1a1a', borderRadius: 4 }}>
        <strong>状态: </strong>
        <span style={{ color: isConnected ? '#4ec9b0' : '#f48771' }}>
          {isConnected ? '🟢 已连接' : '🔴 未连接'}
        </span>
      </div>

      {/* 操作按钮 */}
      <div style={{ marginBottom: 20 }}>
        <button onClick={handleSendPing} disabled={!isConnected} style={{ marginRight: 10 }}>
          发送 Ping
        </button>
        <button onClick={handleReconnect} style={{ marginRight: 10 }}>
          手动重连
        </button>
      </div>

      {/* 订阅任务 */}
      <div style={{ marginBottom: 20 }}>
        <input
          type="text"
          placeholder="输入 task_id"
          value={subscribeTaskId}
          onChange={e => setSubscribeTaskId(e.target.value)}
          style={{ padding: 5, marginRight: 10, width: 200 }}
        />
        <button onClick={handleSubscribe} disabled={!isConnected}>
          订阅任务事件
        </button>
      </div>

      {/* 最新消息 */}
      {lastMessage && (
        <div style={{ marginBottom: 20, padding: 10, background: '#252526', borderRadius: 4 }}>
          <strong>最新消息:</strong>
          <pre style={{ margin: '10px 0 0 0', color: '#9cdcfe' }}>
            {JSON.stringify(lastMessage, null, 2)}
          </pre>
        </div>
      )}

      {/* 日志 */}
      <div>
        <h3>日志</h3>
        <div style={{ background: '#1e1e1e', padding: 10, borderRadius: 4, height: 400, overflowY: 'auto' }}>
          {logs.map((log, i) => (
            <div key={i} style={{ marginBottom: 2, fontSize: 13 }}>
              {log}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
