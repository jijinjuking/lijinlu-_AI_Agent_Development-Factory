// ============================================================
// StatusTag — 通用状态标签组件
// ============================================================

import React from 'react';
import { Tag } from 'antd';

interface StatusTagProps {
  status: string;
  labels?: Record<string, string>;
  colors?: Record<string, string>;
}

/** 默认状态颜色 */
const DEFAULT_COLORS: Record<string, string> = {
  running: 'processing',
  success: 'success',
  completed: 'success',
  failed: 'error',
  error: 'error',
  idle: 'default',
  pending: 'warning',
  waiting: 'warning',
  paused: 'warning',
  review: 'purple',
};

/** 默认状态标签 */
const DEFAULT_LABELS: Record<string, string> = {
  running: '运行中',
  success: '成功',
  completed: '已完成',
  failed: '失败',
  error: '错误',
  idle: '空闲',
  pending: '等待中',
  waiting: '等待中',
  paused: '已暂停',
  todo: '待办',
  in_progress: '进行中',
  review: '审查中',
  done: '已完成',
};

const StatusTag: React.FC<StatusTagProps> = ({ status, labels, colors }) => {
  const mergedLabels = { ...DEFAULT_LABELS, ...labels };
  const mergedColors = { ...DEFAULT_COLORS, ...colors };

  return (
    <Tag color={mergedColors[status] || 'default'}>
      {mergedLabels[status] || status}
    </Tag>
  );
};

export default StatusTag;
