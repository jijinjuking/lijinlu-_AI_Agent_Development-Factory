// ============================================================
// components/event_replay/EventTimeline.tsx
//
// 事件时间线 — 纵向滚动列表，每条事件用彩色圆点+类型+时间展示。
// 当前激活事件高亮显示，点击任意事件可跳转。
// ============================================================

import React, { useEffect, useRef } from 'react';
import { Tag, Tooltip } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, ThunderboltOutlined } from '@ant-design/icons';
import type { RuntimeEvent } from '../../types/event';
import { getEventColor, getEventLabel } from '../../types/event';
import styles from './EventTimeline.module.css';

interface EventTimelineProps {
  events: RuntimeEvent[];
  currentIndex: number;
  onSeek: (index: number) => void;
}

/** 格式化时间戳为 HH:mm:ss.SSS */
function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    const ms = String(d.getMilliseconds()).padStart(3, '0');
    return `${hh}:${mm}:${ss}.${ms}`;
  } catch {
    return iso;
  }
}

/** 根据事件类型选图标 */
function EventTypeIcon({ eventType }: { eventType: string }) {
  if (eventType.endsWith('_completed') || eventType.endsWith('_result')) {
    return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
  }
  if (eventType.endsWith('_failed') || eventType === 'error_occurred') {
    return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
  }
  return <ThunderboltOutlined style={{ color: getEventColor(eventType) }} />;
}

const EventTimeline: React.FC<EventTimelineProps> = ({ events, currentIndex, onSeek }) => {
  const activeRef = useRef<HTMLDivElement>(null);

  // 激活项变化时自动滚动到视图中
  useEffect(() => {
    activeRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [currentIndex]);

  if (events.length === 0) {
    return (
      <div className={styles.emptyPlaceholder}>
        暂无事件数据，请先选择任务加载事件序列
      </div>
    );
  }

  return (
    <div className={styles.timelineContainer}>
      {events.map((event, index) => {
        const isActive = index === currentIndex;
        const isPast = index < currentIndex;

        return (
          <div
            key={event.id}
            ref={isActive ? activeRef : null}
            className={[
              styles.timelineItem,
              isActive ? styles.activeItem : '',
              isPast ? styles.pastItem : '',
            ].join(' ')}
            onClick={() => onSeek(index)}
            title={`点击跳转到第 ${index + 1} 步`}
          >
            {/* 时间线轨道 */}
            <div className={styles.trackLine}>
              <div
                className={styles.dot}
                style={{ backgroundColor: getEventColor(event.event_type) }}
              />
              {index < events.length - 1 && <div className={styles.connector} />}
            </div>

            {/* 内容区 */}
            <div className={styles.content}>
              <div className={styles.header}>
                <EventTypeIcon eventType={event.event_type} />
                <span className={styles.eventTypeLabel}>
                  {getEventLabel(event.event_type)}
                </span>
                <Tag
                  color={getEventColor(event.event_type)}
                  style={{ marginLeft: 4, fontSize: 10 }}
                >
                  {event.event_type}
                </Tag>
              </div>

              <div className={styles.meta}>
                <Tooltip title={event.produced_at}>
                  <span className={styles.timestamp}>
                    {formatTimestamp(event.produced_at)}
                  </span>
                </Tooltip>
                {event.produced_by && (
                  <span className={styles.producer}>by {event.produced_by}</span>
                )}
                <span className={styles.index}>#{index + 1}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default EventTimeline;
