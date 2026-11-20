/**
 * EventsPage - 事件总线监控页面
 * 覆盖: EventBus 事件列表 + SSE 实时推送 + 事件追踪
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Table,
  Button,
  Tag,
  Card,
  Input,
  Space,
  Select,
  DatePicker,
  message,
  Badge,
  Tooltip,
  Switch,
  Typography,
} from 'antd';
import {
  ReloadOutlined,
  ClearOutlined,
  PauseOutlined,
  PlayCircleOutlined,
  FilterOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { fetchEvents, fetchEventStats, type EventRecord } from '../api/events';
import dayjs from 'dayjs';

const { RangePicker } = DatePicker;
const { Text } = Typography;

const eventTypeColors: Record<string, string> = {
  TASK_STARTED: 'processing',
  TASK_COMPLETED: 'success',
  TASK_FAILED: 'error',
  TASK_CANCELED: 'warning',
  AGENT_HEARTBEAT: 'default',
  WORKER_REGISTERED: 'blue',
  WORKER_DEREGISTERED: 'default',
  MODEL_CALL: 'purple',
  POLICY_ALLOW: 'green',
  POLICY_DENY: 'red',
  CHECKPOINT_SAVED: 'cyan',
  LOOP_DETECTED: 'orange',
};

export default function EventsPage() {
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [realtime, setRealtime] = useState(false);
  const [eventTypeFilter, setEventTypeFilter] = useState<string[]>([]);
  const [searchText, setSearchText] = useState('');
  const sseSourceRef = useRef<EventSource | null>(null);

  const loadEvents = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchEvents({
        limit: 200,
        event_type: eventTypeFilter.length > 0 ? eventTypeFilter.join(',') : undefined,
      });
      setEvents(data);
    } catch (e: unknown) {
      message.error(`加载事件失败: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [eventTypeFilter]);

  useEffect(() => {
    loadEvents();
  }, [loadEvents]);

  // SSE 实时订阅
  useEffect(() => {
    if (!realtime) {
      if (sseSourceRef.current) {
        sseSourceRef.current.close();
        sseSourceRef.current = null;
      }
      return;
    }

    const eventSource = new EventSource('/api/v1/events/stream');
    sseSourceRef.current = eventSource;

    eventSource.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        setEvents((prev) => [event, ...prev.slice(0, 199)]);
      } catch {
        // ignore parse errors
      }
    };

    eventSource.onerror = () => {
      // auto-reconnect by browser
    };

    return () => {
      eventSource.close();
    };
  }, [realtime]);

  const handleClear = async () => {
    try {
      // 假设后端有清空事件的接口，如果没有就只清空前端
      setEvents([]);
      message.success('事件已清空');
    } catch {
      message.error('清空失败');
    }
  };

  const filteredEvents = searchText
    ? events.filter(
        (e) =>
          e.id.toString().includes(searchText) ||
          e.event_type?.toLowerCase().includes(searchText.toLowerCase()) ||
          JSON.stringify(e.event_payload || {})
            .toLowerCase()
            .includes(searchText.toLowerCase())
      )
    : events;

  const columns: ColumnsType<EventRecord> = [
    {
      title: '时间',
      dataIndex: 'produced_at',
      key: 'produced_at',
      width: 180,
      render: (ts: string) => (
        <Text type="secondary">{dayjs(ts).format('YYYY-MM-DD HH:mm:ss')}</Text>
      ),
    },
    {
      title: '事件类型',
      dataIndex: 'event_type',
      key: 'event_type',
      width: 200,
      render: (type: string) => (
        <Tag color={eventTypeColors[type] || 'default'}>{type}</Tag>
      ),
    },
    {
      title: '关联 ID',
      dataIndex: 'task_id',
      key: 'task_id',
      width: 220,
      ellipsis: true,
      render: (id: string) => id || '-',
    },
    {
      title: '来源',
      dataIndex: 'produced_by',
      key: 'produced_by',
      width: 120,
    },
    {
      title: '负载',
      dataIndex: 'event_payload',
      key: 'event_payload',
      ellipsis: true,
      render: (payload: Record<string, unknown>) => (
        <Tooltip title={JSON.stringify(payload, null, 2)}>
          <Text code style={{ fontSize: 12 }}>
            {JSON.stringify(payload).slice(0, 80)}
            {(JSON.stringify(payload).length > 80) && '...'}
          </Text>
        </Tooltip>
      ),
    },
  ];

  return (
    <div>
      <Card
        title="事件总线监控"
        extra={
          <Space>
            <Space size="small">
              <Text type="secondary">实时推送</Text>
              <Switch
                checked={realtime}
                onChange={setRealtime}
                checkedChildren={<PlayCircleOutlined />}
                unCheckedChildren={<PauseOutlined />}
              />
            </Space>
            <Select
              mode="multiple"
              placeholder="筛选事件类型"
              style={{ width: 260 }}
              value={eventTypeFilter}
              onChange={setEventTypeFilter}
              allowClear
              options={Object.keys(eventTypeColors).map((k) => ({ label: k, value: k }))}
            />
            <Input.Search
              placeholder="搜索事件..."
              allowClear
              style={{ width: 200 }}
              onSearch={setSearchText}
              onChange={(e) => !e.target.value && setSearchText('')}
            />
            <Button icon={<ReloadOutlined />} onClick={loadEvents} loading={loading}>
              刷新
            </Button>
            <Button icon={<ClearOutlined />} onClick={handleClear} danger>
              清空
            </Button>
          </Space>
        }
      >
        <Table
          rowKey="event_id"
          columns={columns}
          dataSource={filteredEvents}
          loading={loading}
          pagination={{ pageSize: 50, showSizeChanger: true, pageSizeOptions: ['20', '50', '100'] }}
          scroll={{ x: 900 }}
          size="small"
        />
      </Card>
    </div>
  );
}
