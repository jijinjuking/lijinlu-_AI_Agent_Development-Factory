// ============================================================
// components/event_replay/TaskSelectorPanel.tsx
//
// 任务选择面板：输入 Task ID 或从最近任务列表中选择，
// 点击「加载事件」触发回放序列加载
// ============================================================

import React, { useState } from 'react';
import { Input, Button, Select, Space, Typography, Spin } from 'antd';
import { SearchOutlined, ReloadOutlined } from '@ant-design/icons';

const { Text } = Typography;

interface TaskSelectorPanelProps {
  loading: boolean;
  onLoadTask: (taskId: string) => void;
}

const TaskSelectorPanel: React.FC<TaskSelectorPanelProps> = ({ loading, onLoadTask }) => {
  const [inputTaskId, setInputTaskId] = useState('');

  const handleLoad = () => {
    const trimmed = inputTaskId.trim();
    if (trimmed) onLoadTask(trimmed);
  };

  return (
    <Space.Compact style={{ width: '100%', maxWidth: 500 }}>
      <Input
        placeholder="输入 Task ID（UUID）..."
        value={inputTaskId}
        onChange={(e) => setInputTaskId(e.target.value)}
        onPressEnter={handleLoad}
        prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
        allowClear
      />
      <Button
        type="primary"
        icon={loading ? <Spin size="small" /> : <ReloadOutlined />}
        onClick={handleLoad}
        disabled={!inputTaskId.trim() || loading}
        loading={loading}
      >
        加载事件
      </Button>
    </Space.Compact>
  );
};

export default TaskSelectorPanel;
