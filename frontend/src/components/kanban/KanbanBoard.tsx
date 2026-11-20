// ============================================================
// KanbanBoard — 看板主组件（DnD 拖拽支持）
// ============================================================

import React, { useEffect, useState } from 'react';
import {
  DndContext,
  DragOverlay,
  closestCorners,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import type { DragStartEvent, DragEndEvent } from '@dnd-kit/core';
import { Spin, Empty } from 'antd';
import { useKanbanStore } from '../../stores/kanbanStore';
import type { KanbanTask, KanbanColumnType } from '../../types/agent';
import KanbanColumn from './KanbanColumn';
import TaskCard from './TaskCard';

const KanbanBoard: React.FC = () => {
  const { columns, isLoading, loadData, moveTask } = useKanbanStore();
  const [activeTask, setActiveTask] = useState<KanbanTask | null>(null);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 5 }, // 5px 后才激活拖拽，避免误触
    })
  );

  function handleDragStart(event: DragStartEvent) {
    const task = event.active.data.current?.task as KanbanTask | undefined;
    setActiveTask(task ?? null);
  }

  function handleDragEnd(event: DragEndEvent) {
    setActiveTask(null);

    const { active, over } = event;
    if (!over) return;

    const taskId = active.id as string;
    const fromCol = active.data.current?.task?.status as KanbanColumnType | undefined;
    const toCol = over.id as KanbanColumnType;

    if (!fromCol || fromCol === toCol) return;

    // 找到目标列的插入位置
    const toColumn = columns.find((c) => c.type === toCol);
    const toIndex = toColumn ? toColumn.tasks.length : 0;

    moveTask(taskId, fromCol, toCol, toIndex);
  }

  if (isLoading && columns.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <Spin size="large" description="加载 Agent 任务..." />
      </div>
    );
  }

  if (columns.length === 0) {
    return <Empty description="暂无数据" style={{ padding: 60 }} />;
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div
        style={{
          display: 'flex',
          gap: 16,
          overflowX: 'auto',
          overflowY: 'hidden',
          paddingBottom: 16,
          minHeight: 400,
        }}
      >
        {columns.map((col) => (
          <KanbanColumn key={col.id} column={col} />
        ))}
      </div>

      {/* 拖拽时的浮动卡片 */}
      <DragOverlay dropAnimation={null}>
        {activeTask ? <TaskCard task={activeTask} isDragging /> : null}
      </DragOverlay>
    </DndContext>
  );
};

export default KanbanBoard;
