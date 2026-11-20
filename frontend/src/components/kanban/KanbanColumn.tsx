// ============================================================
// KanbanColumn — 看板单列（可放置区域）
// ============================================================

import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Typography, Badge } from 'antd';
import type { KanbanColumn as KanbanColumnType, KanbanColumnType as ColType } from '../../types/agent';
import TaskCard from './TaskCard';

const { Text } = Typography;

/** 列头颜色 */
const COLUMN_COLORS: Record<ColType, string> = {
  todo: '#8c8c8c',
  in_progress: '#1677ff',
  review: '#fa8c16',
  done: '#52c41a',
  failed: '#ff4d4f',
};

interface KanbanColumnProps {
  column: KanbanColumnType;
}

const KanbanColumn: React.FC<KanbanColumnProps> = ({ column }) => {
  const { setNodeRef, isOver } = useDroppable({
    id: column.type,
    data: { columnType: column.type },
  });

  const headerColor = COLUMN_COLORS[column.type] || '#8c8c8c';

  return (
    <div
      ref={setNodeRef}
      style={{
        minWidth: 280,
        maxWidth: 320,
        flex: '0 0 auto',
        background: isOver ? 'rgba(22, 119, 255, 0.08)' : 'var(--ant-color-bg-container, #161b22)',
        borderRadius: 8,
        padding: '12px',
        display: 'flex',
        flexDirection: 'column',
        maxHeight: 'calc(100vh - 160px)',
        border: isOver ? '2px dashed #1677ff' : '2px solid transparent',
        transition: 'background 0.2s, border 0.2s',
      }}
    >
      {/* 列头 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingBottom: 12,
          borderBottom: `2px solid ${headerColor}`,
          marginBottom: 8,
        }}
      >
        <Text strong style={{ fontSize: 14 }}>
          {column.title}
        </Text>
        <Badge
          count={column.tasks.length}
          style={{ backgroundColor: headerColor }}
          overflowCount={99}
        />
      </div>

      {/* 任务列表 */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          overflowX: 'hidden',
          paddingRight: 4,
          minHeight: 80,
        }}
      >
        {column.tasks.map((task) => (
          <TaskCard key={task.id} task={task} />
        ))}

        {column.tasks.length === 0 && (
          <div
            style={{
              textAlign: 'center',
              padding: 24,
              color: '#8c8c8c',
              fontSize: 13,
            }}
          >
            {isOver ? '松开以放置' : '暂无任务'}
          </div>
        )}
      </div>
    </div>
  );
};

export default KanbanColumn;
