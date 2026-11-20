// ============================================================
// components/event_replay/EventDetailPanel.tsx
//
// 事件详情面板：展示当前激活事件的类型、时间、生产者、
// 以及完整的 event_payload（JSON 树形展示）
// ============================================================

import React from 'react';
import { Descriptions, Tag, Typography, Empty, Divider } from 'antd';
import { CalendarOutlined, UserOutlined, TagOutlined } from '@ant-design/icons';
import type { RuntimeEvent } from '../../types/event';
import { getEventColor, getEventLabel } from '../../types/event';

const { Text, Title } = Typography;

interface EventDetailPanelProps {
  event: RuntimeEvent | null;
  eventIndex: number;
  totalEvents: number;
}

/** 递归渲染 JSON 对象为可折叠的树状结构 */
function JsonTreeNode({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) {
    return <Text type="secondary">null</Text>;
  }
  if (typeof value === 'boolean') {
    return <Text style={{ color: value ? '#52c41a' : '#ff4d4f' }}>{String(value)}</Text>;
  }
  if (typeof value === 'number') {
    return <Text style={{ color: '#1677ff' }}>{value}</Text>;
  }
  if (typeof value === 'string') {
    if (value.length > 200) {
      return <Text style={{ color: '#595959', wordBreak: 'break-all' }}>&quot;{value.slice(0, 200)}...&quot;</Text>;
    }
    return <Text style={{ color: '#595959' }}>&quot;{value}&quot;</Text>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <Text type="secondary">[]</Text>;
    return (
      <div style={{ marginLeft: depth > 0 ? 16 : 0 }}>
        {value.map((item, i) => (
          <div key={i} style={{ display: 'flex', gap: 4 }}>
            <Text type="secondary" style={{ fontSize: 11, minWidth: 20 }}>[{i}]</Text>
            <JsonTreeNode value={item} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <Text type="secondary">{'{}'}</Text>;
    return (
      <div style={{ marginLeft: depth > 0 ? 16 : 0 }}>
        {entries.map(([key, val]) => (
          <div key={key} style={{ display: 'flex', gap: 6, marginBottom: 2, flexWrap: 'wrap' }}>
            <Text strong style={{ color: '#8c8c8c', fontSize: 12, minWidth: 80 }}>{key}:</Text>
            <JsonTreeNode value={val} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }
  return <Text>{String(value)}</Text>;
}

const EventDetailPanel: React.FC<EventDetailPanelProps> = ({ event, eventIndex, totalEvents }) => {
  if (!event) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="请选择或回放到某个事件以查看详情" imageStyle={{ height: 48 }} />
      </div>
    );
  }

  return (
    <div style={{ padding: '12px 16px', overflow: 'auto', height: '100%' }}>
      {/* 标题区 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <Title level={5} style={{ margin: 0 }}>
          事件详情
        </Title>
        <Text type="secondary" style={{ fontSize: 12 }}>
          第 {eventIndex + 1} 步 / 共 {totalEvents} 步
        </Text>
      </div>

      {/* 基础信息 */}
      <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item
          label={<><TagOutlined /> 事件类型</>}
        >
          <Tag color={getEventColor(event.event_type)}>{event.event_type}</Tag>
          <Text style={{ marginLeft: 4, color: '#595959' }}>{getEventLabel(event.event_type)}</Text>
        </Descriptions.Item>

        <Descriptions.Item label={<><CalendarOutlined /> 发生时间</>}>
          <Text code style={{ fontSize: 12 }}>{event.produced_at}</Text>
        </Descriptions.Item>

        <Descriptions.Item label={<><UserOutlined /> 生产者</>}>
          {event.produced_by ? (
            <Tag>{event.produced_by}</Tag>
          ) : (
            <Text type="secondary">—</Text>
          )}
        </Descriptions.Item>

        {event.task_id && (
          <Descriptions.Item label="Task ID">
            <Text copyable style={{ fontSize: 11, fontFamily: 'monospace' }}>{event.task_id}</Text>
          </Descriptions.Item>
        )}

        <Descriptions.Item label="Event ID">
          <Text style={{ fontSize: 11, fontFamily: 'monospace' }}>#{event.id}</Text>
        </Descriptions.Item>
      </Descriptions>

      <Divider style={{ margin: '8px 0' }}>Payload</Divider>

      {/* Payload 展示 */}
      <div
        style={{
          background: '#f6f8fa',
          border: '1px solid #e8e8e8',
          borderRadius: 6,
          padding: '10px 12px',
          fontFamily: 'monospace',
          fontSize: 12,
          lineHeight: 1.6,
          maxHeight: 400,
          overflow: 'auto',
        }}
      >
        {Object.keys(event.event_payload || {}).length === 0 ? (
          <Text type="secondary">（空 Payload）</Text>
        ) : (
          <JsonTreeNode value={event.event_payload} />
        )}
      </div>
    </div>
  );
};

export default EventDetailPanel;
