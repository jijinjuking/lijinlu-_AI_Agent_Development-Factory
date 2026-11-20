// ============================================================
// AgentsPage — Agent 看板页面（含 SSE 实时事件）
// ============================================================

import React, { useEffect } from 'react';
import { Typography, Space, Badge } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import KanbanBoard from '../components/kanban/KanbanBoard';
import { useKanbanStore } from '../stores/kanbanStore';
import { useSSE } from '../hooks/useSSE';

const { Title, Text } = Typography;

const AgentsPage: React.FC = () => {
  const { isLoading, loadData, handleSSEEvent } = useKanbanStore();

  // 初始加载
  useEffect(() => {
    loadData();
  }, [loadData]);

  // SSE 实时事件订阅（全局）
  useSSE(null, (event) => {
    handleSSEEvent(event.event, event.data);
  });

  return (
    <div>
      {/* 页面标题 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 20,
        }}
      >
        <div>
          <Title level={4} style={{ margin: 0 }}>
            Agent 任务看板
          </Title>
          <Text type="secondary" style={{ fontSize: 13 }}>
            实时追踪每个 Agent 的工作状态和任务进度
          </Text>
        </div>
        <Space>
          <Badge status="processing" text="实时" />
          <ReloadOutlined
            onClick={loadData}
            spin={isLoading}
            style={{ fontSize: 16, cursor: 'pointer' }}
          />
        </Space>
      </div>

      <KanbanBoard />
    </div>
  );
};

export default AgentsPage;
