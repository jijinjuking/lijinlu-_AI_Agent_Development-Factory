// ============================================================
// components/event_replay/StateSnapshotViewer.tsx
//
// 状态快照查看器：从 state_updated / checkpoint_saved 类型事件的
// payload 中提取状态快照，以结构化方式展示当前节点/状态。
// 若当前事件不含快照，则展示上一个已知快照（保留最后一个有效状态）。
// ============================================================

import React, { useMemo } from 'react';
import { Descriptions, Tag, Empty, Typography, Progress, Badge } from 'antd';
import { DatabaseOutlined } from '@ant-design/icons';
import type { RuntimeEvent } from '../../types/event';

const { Text, Title } = Typography;

// 包含状态信息的事件类型
const STATE_BEARING_TYPES = new Set([
  'state_updated',
  'checkpoint_saved',
  'task_started',
  'task_completed',
  'task_failed',
  'node_entered',
  'node_exited',
]);

/** 从事件序列中提取截至 currentIndex 的最后一个状态快照 */
function extractLatestSnapshot(
  events: RuntimeEvent[],
  upToIndex: number,
): Record<string, unknown> | null {
  for (let i = upToIndex; i >= 0; i--) {
    const event = events[i];
    if (STATE_BEARING_TYPES.has(event.event_type)) {
      const payload = event.event_payload;
      // 优先取 state_snapshot 或 state 字段
      if (payload?.state_snapshot && typeof payload.state_snapshot === 'object') {
        return payload.state_snapshot as Record<string, unknown>;
      }
      if (payload?.state && typeof payload.state === 'object') {
        return payload.state as Record<string, unknown>;
      }
      // node_entered / node_exited 可以构造伪快照
      if (event.event_type === 'node_entered' || event.event_type === 'node_exited') {
        return {
          current_node: payload?.node_name ?? '—',
          workflow_status: event.event_type === 'node_entered' ? 'running' : 'transitioning',
          ...((payload?.extra as object) ?? {}),
        };
      }
    }
  }
  return null;
}

/** 工作流状态颜色 */
function workflowStatusBadge(status: unknown): React.ReactNode {
  const statusStr = String(status ?? '');
  const statusMap: Record<string, 'processing' | 'success' | 'error' | 'default' | 'warning'> = {
    running: 'processing',
    completed: 'success',
    failed: 'error',
    pending: 'default',
    paused: 'warning',
    transitioning: 'warning',
  };
  return (
    <Badge
      status={statusMap[statusStr] ?? 'default'}
      text={<Text style={{ fontSize: 12 }}>{statusStr || '—'}</Text>}
    />
  );
}

interface StateSnapshotViewerProps {
  events: RuntimeEvent[];
  currentIndex: number;
}

const StateSnapshotViewer: React.FC<StateSnapshotViewerProps> = ({ events, currentIndex }) => {
  const snapshot = useMemo(
    () => extractLatestSnapshot(events, currentIndex),
    [events, currentIndex],
  );

  const nodeHistory: string[] = useMemo(() => {
    const seen: string[] = [];
    for (let i = 0; i <= currentIndex; i++) {
      const ev = events[i];
      if (ev?.event_type === 'node_entered') {
        const node = ev.event_payload?.node_name;
        if (typeof node === 'string' && !seen.includes(node)) {
          seen.push(node);
        }
      }
    }
    return seen;
  }, [events, currentIndex]);

  const completedNodeCount = useMemo(() => {
    let count = 0;
    for (let i = 0; i <= currentIndex; i++) {
      if (events[i]?.event_type === 'node_exited') count++;
    }
    return count;
  }, [events, currentIndex]);

  if (!snapshot) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="当前事件不含状态快照" imageStyle={{ height: 48 }} />
      </div>
    );
  }

  const currentNode = String(snapshot?.current_node ?? '—');
  const workflowStatus = snapshot?.workflow_status;
  const goal = String(snapshot?.goal ?? '');
  const contextSizeBytes = snapshot?.context_size_bytes as number | undefined;

  return (
    <div style={{ padding: '12px 16px', overflow: 'auto', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <DatabaseOutlined style={{ color: '#1677ff' }} />
        <Title level={5} style={{ margin: 0 }}>运行时状态快照</Title>
        <Text type="secondary" style={{ fontSize: 11 }}>（截至第 {currentIndex + 1} 步）</Text>
      </div>

      {/* 核心字段 */}
      <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item label="当前节点">
          <Tag color="purple">{currentNode}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="工作流状态">
          {workflowStatusBadge(workflowStatus)}
        </Descriptions.Item>
        {goal && (
          <Descriptions.Item label="任务目标">
            <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: goal }}>{goal}</Text>
          </Descriptions.Item>
        )}
        {typeof contextSizeBytes === 'number' && (
          <Descriptions.Item label="Context 大小">
            <Text code style={{ fontSize: 11 }}>{contextSizeBytes.toLocaleString()} bytes</Text>
            <Progress
              percent={Math.min(100, Math.round(contextSizeBytes / 1000))}
              size="small"
              showInfo={false}
              style={{ marginTop: 4 }}
            />
          </Descriptions.Item>
        )}
        <Descriptions.Item label="已执行节点">
          <Text>{completedNodeCount}</Text>
          {nodeHistory.length > 0 && (
            <div style={{ marginTop: 4 }}>
              {nodeHistory.map((node) => (
                <Tag key={node} style={{ marginBottom: 2 }}>{node}</Tag>
              ))}
            </div>
          )}
        </Descriptions.Item>
      </Descriptions>

      {/* 原始快照 key-value（排除已展示字段） */}
      {Object.keys(snapshot).length > 0 && (
        <>
          <Text type="secondary" style={{ fontSize: 11 }}>原始字段</Text>
          <div
            style={{
              background: '#f6f8fa',
              border: '1px solid #e8e8e8',
              borderRadius: 6,
              padding: '8px 10px',
              marginTop: 4,
              fontSize: 11,
              fontFamily: 'monospace',
              maxHeight: 200,
              overflow: 'auto',
            }}
          >
            {Object.entries(snapshot)
              .filter(([key]) => !['current_node', 'workflow_status', 'goal', 'context_size_bytes'].includes(key))
              .map(([key, val]) => (
                <div key={key} style={{ marginBottom: 2 }}>
                  <Text strong style={{ color: '#8c8c8c', marginRight: 6 }}>{key}:</Text>
                  <Text style={{ color: '#595959' }}>
                    {typeof val === 'object' ? JSON.stringify(val) : String(val ?? '—')}
                  </Text>
                </div>
              ))}
          </div>
        </>
      )}
    </div>
  );
};

export default StateSnapshotViewer;
