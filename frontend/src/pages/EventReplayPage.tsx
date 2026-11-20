// ============================================================
// pages/EventReplayPage.tsx — W19 Event Replay 主页面
//
// 布局（三栏 + 底部控制栏）：
//   ┌────────────────────────────────────────────────────────┐
//   │  Header：任务选择 + 统计信息                             │
//   ├──────────────┬────────────────────┬────────────────────┤
//   │  左栏         │  中栏              │  右栏              │
//   │  EventTimeline│  EventDetailPanel  │ StateSnapshotViewer│
//   ├──────────────┴────────────────────┴────────────────────┤
//   │  ReplayController（进度条 + 控制按钮）                   │
//   └────────────────────────────────────────────────────────┘
// ============================================================

import React, { useCallback, useEffect } from 'react';
import {
  Typography,
  Alert,
  Statistic,
  Row,
  Col,
  Card,
  Divider,
  Empty,
  Spin,
} from 'antd';
import {
  ThunderboltOutlined,
  ClockCircleOutlined,
  AppstoreOutlined,
} from '@ant-design/icons';

import { useEventReplayStore } from '../stores/eventReplayStore';
import EventTimeline from '../components/event_replay/EventTimeline';
import ReplayController from '../components/event_replay/ReplayController';
import EventDetailPanel from '../components/event_replay/EventDetailPanel';
import StateSnapshotViewer from '../components/event_replay/StateSnapshotViewer';
import TaskSelectorPanel from '../components/event_replay/TaskSelectorPanel';

const { Title, Text } = Typography;

// ── 统计卡片 ─────────────────────────────────────────────

function StatsBar({ events }: { events: Array<{ event_type: string }> }) {
  const typeCount: Record<string, number> = {};
  for (const ev of events) {
    typeCount[ev.event_type] = (typeCount[ev.event_type] ?? 0) + 1;
  }
  const uniqueTypes = Object.keys(typeCount).length;

  return (
    <Row gutter={16} style={{ marginTop: 8, marginBottom: 4 }}>
      <Col>
        <Statistic
          title="事件总数"
          value={events.length}
          prefix={<ThunderboltOutlined />}
          styles={{ content: { fontSize: 18 } }}
        />
      </Col>
      <Col>
        <Statistic
          title="事件类型"
          value={uniqueTypes}
          prefix={<AppstoreOutlined />}
          styles={{ content: { fontSize: 18 } }}
        />
      </Col>
    </Row>
  );
}

// ── 主页面组件 ────────────────────────────────────────────

const EventReplayPage: React.FC = () => {
  const {
    isLoadingEvents,
    eventsError,
    replay,
    loadTaskEventsForReplay,
    startReplay,
    pauseReplay,
    stopReplay,
    seekTo,
    stepForward,
    stepBackward,
    setSpeed,
  } = useEventReplayStore();

  const { events, currentIndex, status, speed, activeEvent } = replay;

  // 加载任务事件序列
  const handleLoadTask = useCallback(
    (taskId: string) => {
      loadTaskEventsForReplay(taskId);
    },
    [loadTaskEventsForReplay],
  );

  // 离开页面时停止回放
  useEffect(() => {
    return () => {
      pauseReplay();
    };
  }, [pauseReplay]);

  // ── 三栏内容高度（减去 Header + 控制栏） ──────────────
  const PANEL_HEIGHT = 'calc(100vh - 280px)';

  return (
    <div style={{ padding: '20px 24px', height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* ── Header ──────────────────────────────────────── */}
      <div style={{ marginBottom: 12 }}>
        <Title level={4} style={{ margin: 0 }}>
          <ThunderboltOutlined style={{ marginRight: 8, color: '#1677ff' }} />
          事件回放
        </Title>
        <Text type="secondary" style={{ fontSize: 13 }}>
          加载任务的历史事件序列，按时间轴逐步回放 Agent 执行过程
        </Text>
      </div>

      {/* ── 任务选择 ──────────────────────────────────────── */}
      <Card size="small" style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 24, flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 300 }}>
            <Text strong style={{ display: 'block', marginBottom: 6 }}>选择任务</Text>
            <TaskSelectorPanel loading={isLoadingEvents} onLoadTask={handleLoadTask} />
          </div>
          {events.length > 0 && (
            <div>
              <StatsBar events={events} />
            </div>
          )}
        </div>
      </Card>

      {/* ── 错误提示 ──────────────────────────────────────── */}
      {eventsError && (
        <Alert
          type="error"
          message={eventsError}
          closable
          style={{ marginBottom: 12 }}
        />
      )}

      {/* ── 加载中 ────────────────────────────────────────── */}
      {isLoadingEvents && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin size="large" tip="正在加载事件序列..." />
        </div>
      )}

      {/* ── 三栏回放区 ──────────────────────────────────── */}
      {!isLoadingEvents && events.length === 0 && !eventsError && (
        <Card style={{ flex: 1 }}>
          <Empty description="输入 Task ID 并点击「加载事件」开始回放" />
        </Card>
      )}

      {!isLoadingEvents && events.length > 0 && (
        <div
          style={{
            flex: 1,
            display: 'grid',
            gridTemplateColumns: '260px 1fr 1fr',
            gridTemplateRows: `${PANEL_HEIGHT} auto`,
            gap: 0,
            border: '1px solid #e8e8e8',
            borderRadius: 8,
            overflow: 'hidden',
            background: '#fff',
          }}
        >
          {/* 左栏：事件时间线 */}
          <div
            style={{
              borderRight: '1px solid #f0f0f0',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <div
              style={{
                padding: '8px 12px',
                borderBottom: '1px solid #f0f0f0',
                background: '#fafafa',
              }}
            >
              <Text strong style={{ fontSize: 12 }}>事件时间线</Text>
              <Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>
                {events.length} 条
              </Text>
            </div>
            <div style={{ flex: 1, overflow: 'hidden' }}>
              <EventTimeline
                events={events}
                currentIndex={currentIndex}
                onSeek={seekTo}
              />
            </div>
          </div>

          {/* 中栏：事件详情 */}
          <div
            style={{
              borderRight: '1px solid #f0f0f0',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <div
              style={{
                padding: '8px 12px',
                borderBottom: '1px solid #f0f0f0',
                background: '#fafafa',
              }}
            >
              <Text strong style={{ fontSize: 12 }}>事件详情</Text>
            </div>
            <div style={{ flex: 1, overflow: 'auto' }}>
              <EventDetailPanel
                event={activeEvent}
                eventIndex={currentIndex}
                totalEvents={events.length}
              />
            </div>
          </div>

          {/* 右栏：状态快照 */}
          <div style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div
              style={{
                padding: '8px 12px',
                borderBottom: '1px solid #f0f0f0',
                background: '#fafafa',
              }}
            >
              <Text strong style={{ fontSize: 12 }}>状态快照</Text>
            </div>
            <div style={{ flex: 1, overflow: 'auto' }}>
              <StateSnapshotViewer events={events} currentIndex={currentIndex} />
            </div>
          </div>

          {/* 底栏：回放控制器（横跨三栏） */}
          <div style={{ gridColumn: '1 / -1', borderTop: '1px solid #e8e8e8' }}>
            <ReplayController
              status={status}
              currentIndex={currentIndex}
              totalEvents={events.length}
              speed={speed}
              onPlay={startReplay}
              onPause={pauseReplay}
              onStop={stopReplay}
              onStepForward={stepForward}
              onStepBackward={stepBackward}
              onSeek={seekTo}
              onSpeedChange={setSpeed}
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default EventReplayPage;
