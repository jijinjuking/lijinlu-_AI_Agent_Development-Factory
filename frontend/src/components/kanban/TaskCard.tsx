// ============================================================
// TaskCard — 看板任务卡片（可拖拽，支持执行/取消/分配 Agent）
// ============================================================

import React, { useEffect, useState, useCallback } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { Card, Tag, Typography, Space, Tooltip, Button, App, Select } from 'antd';
import {
  ClockCircleOutlined,
  ThunderboltOutlined,
  DollarOutlined,
  PlayCircleOutlined,
  StopOutlined,
  UserOutlined,
  LoadingOutlined,
} from '@ant-design/icons';
import type { KanbanTask, Agent } from '../../types/agent';
import { useKanbanStore } from '../../stores/kanbanStore';
import { fetchAgents } from '../../api/agents';

const { Text } = Typography;

/** 优先级配置 */
const PRIORITY_CONFIG: Record<string, { label: string; color: string }> = {
  critical: { label: '紧急', color: '#ff4d4f' },
  high: { label: '高', color: '#fa8c16' },
  medium: { label: '中', color: '#1677ff' },
  low: { label: '低', color: '#8c8c8c' },
};

/** 格式化耗时 */
function formatDuration(ms?: number): string {
  if (!ms) return '-';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

interface TaskCardProps {
  task: KanbanTask;
  isDragging?: boolean;
}

const TaskCard: React.FC<TaskCardProps> = ({ task, isDragging }) => {
  const { executeTask, cancelTask, updateTask } = useKanbanStore();
  const { message } = App.useApp();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentsLoaded, setAgentsLoaded] = useState(false);

  // 懒加载 Agent 列表
  const loadAgents = useCallback(async () => {
    if (agentsLoaded) return;
    try {
      const list = await fetchAgents(); // 不按 status 过滤，确保所有 Agent 可分配
      setAgents(list);
      setAgentsLoaded(true);
    } catch {
      // 静默失败
    }
  }, [agentsLoaded]);

  const { attributes, listeners, setNodeRef, transform } = useDraggable({
    id: task.id,
    data: { task },
  });

  const priority = PRIORITY_CONFIG[task.priority] || PRIORITY_CONFIG.medium;
  const isInTodo = task.status === 'todo';
  const isRunning = task.status === 'in_progress' || (task.status as string) === 'running' || (task.status as string) === 'thinking';

  const handleExecute = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!task.agentId) {
      message.warning('请先为此任务分配 Agent');
      return;
    }
    try {
      await executeTask(task.id);
      message.success(`任务 "${task.title}" 已开始执行`);
    } catch (err: any) {
      message.error(err?.message || '执行失败');
    }
  };

  const handleCancel = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await cancelTask(task.id);
      message.info(`任务 "${task.title}" 已取消`);
    } catch (err: any) {
      message.error(err?.message || '取消失败');
    }
  };

  const handleAgentChange = (agentId: string) => {
    const agent = agents.find((a) => a.id === agentId);
    updateTask(task.id, {
      agentId: agentId || null,
      agentName: agent?.name || '未分配',
    });
    message.success(agent ? `已分配 Agent: ${agent.name}` : '已取消分配');
  };

  const style: React.CSSProperties = {
    marginBottom: 8,
    cursor: 'grab',
    borderLeft: `3px solid ${priority.color}`,
    opacity: isDragging ? 0.5 : 1,
    ...(isRunning
      ? {
          animation: 'pulse-border 1.5s ease-in-out infinite',
          boxShadow: '0 0 8px rgba(22, 119, 255, 0.3)',
        }
      : {}),
    ...(transform
      ? {
          transform: `translate(${transform.x}px, ${transform.y}px)`,
          zIndex: 999,
        }
      : {}),
  };

  return (
    <div ref={setNodeRef} {...listeners} {...attributes}>
      {/* 脉冲动画 keyframes */}
      <style>{`
        @keyframes pulse-border {
          0%, 100% { box-shadow: 0 0 4px rgba(22, 119, 255, 0.2); }
          50% { box-shadow: 0 0 14px rgba(22, 119, 255, 0.5); }
        }
      `}</style>
      <Card size="small" style={style} styles={{ body: { padding: '10px 12px' } }} hoverable>
        {/* 标题行 + 操作按钮 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Text strong style={{ fontSize: 13, wordBreak: 'break-word' }}>
              {task.title}
            </Text>
            {/* 思考状态消息 */}
            {(task as any)._thinking && (
              <div style={{
                fontSize: 11,
                color: '#1677ff',
                marginTop: 4,
                display: 'flex',
                alignItems: 'center',
                gap: 4,
              }}>
                <LoadingOutlined style={{ fontSize: 11 }} />
                <span>{(task as any)._thinking}</span>
              </div>
            )}
          </div>
          <Space size={2} style={{ marginLeft: 4, flexShrink: 0 }}>
            {isInTodo && (
              <Tooltip title="执行">
                <Button
                  type="text"
                  size="small"
                  icon={<PlayCircleOutlined style={{ color: '#52c41a' }} />}
                  onClick={handleExecute}
                  style={{ padding: '0 2px', height: 22 }}
                />
              </Tooltip>
            )}
            {isRunning && (
              <Tooltip title="取消">
                <Button
                  type="text"
                  size="small"
                  icon={<StopOutlined style={{ color: '#ff4d4f' }} />}
                  onClick={handleCancel}
                  style={{ padding: '0 2px', height: 22 }}
                />
              </Tooltip>
            )}
          </Space>
        </div>

        {/* 标签 */}
        <Space size={4} wrap style={{ marginBottom: 8 }}>
          <Tag color={priority.color} style={{ fontSize: 11, lineHeight: '18px' }}>
            {priority.label}
          </Tag>
          {task.tags.slice(0, 2).map((tag) => (
            <Tag key={tag} style={{ fontSize: 11, lineHeight: '18px' }}>
              {tag}
            </Tag>
          ))}
        </Space>

        {/* 元信息 */}
        <Space
          size={8}
          style={{
            fontSize: 11,
            color: '#8c8c8c',
            flexWrap: 'wrap',
          }}
        >
          {/* Agent 选择器 */}
          <Tooltip title={task.agentId ? `点击切换 Agent` : '点击分配 Agent'}>
            <Select
              size="small"
              placeholder="未分配"
              value={task.agentId || undefined}
              onChange={handleAgentChange}
              onOpenChange={(open) => { if (open) loadAgents(); }}
              onClick={(e) => e.stopPropagation()}
              style={{ minWidth: 100, fontSize: 11 }}
              styles={{ popup: { root: { fontSize: 12 } } }}
              allowClear
              options={agents.map((a) => ({
                value: a.id,
                label: a.name,
              }))}
              notFoundContent="无可用 Agent"
              suffixIcon={<UserOutlined style={{ fontSize: 10 }} />}
            />
          </Tooltip>

          {task.tokenUsage !== undefined && (
            <span>
              <ThunderboltOutlined style={{ marginRight: 2 }} />
              {task.tokenUsage >= 1000
                ? `${(task.tokenUsage / 1000).toFixed(1)}k`
                : task.tokenUsage}
            </span>
          )}

          {task.cost !== undefined && (
            <span>
              <DollarOutlined style={{ marginRight: 2 }} />
              ¥{task.cost.toFixed(2)}
            </span>
          )}

          {task.duration !== undefined && (
            <span>
              <ClockCircleOutlined style={{ marginRight: 2 }} />
              {formatDuration(task.duration)}
            </span>
          )}
        </Space>
      </Card>
    </div>
  );
};

export default TaskCard;
