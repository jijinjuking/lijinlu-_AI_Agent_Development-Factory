// ============================================================
// RecentActivity — 最近活动时间线（真实 API + 多源活动类型）
// ============================================================

import React, { useEffect, useState } from 'react';
import { Card, Timeline, Typography, Space, Tag } from 'antd';
import {
  RobotOutlined,
  NodeIndexOutlined,
  WarningOutlined,
  AuditOutlined,
  CheckCircleOutlined,
  SyncOutlined,
  CloseCircleOutlined,
  DollarOutlined,
  ApiOutlined,
} from '@ant-design/icons';
import { fetchActivities } from '../../api/dashboard';
import type { RecentActivity } from '../../types/common';

const { Title, Text } = Typography;

/** 活动类型图标映射 */
const activityIcons: Record<string, React.ReactNode> = {
  agent_start: <RobotOutlined style={{ color: '#1677ff' }} />,
  agent_complete: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  agent_event: <RobotOutlined style={{ color: '#1677ff' }} />,
  pipeline_run: <NodeIndexOutlined style={{ color: '#722ed1' }} />,
  llm_call: <ApiOutlined style={{ color: '#fa8c16' }} />,
  error: <WarningOutlined style={{ color: '#ff4d4f' }} />,
  review: <AuditOutlined style={{ color: '#fa8c16' }} />,
};

/** 活动类型文字标签 */
const typeLabels: Record<string, string> = {
  agent_start: 'Agent',
  agent_complete: 'Agent',
  agent_event: 'Agent',
  pipeline_run: '流程',
  llm_call: '模型',
  error: '异常',
  review: '审批',
};

/** 活动类型标签颜色 */
const typeColors: Record<string, string> = {
  agent_start: 'blue',
  agent_complete: 'green',
  agent_event: 'blue',
  pipeline_run: 'purple',
  llm_call: 'orange',
  error: 'red',
  review: 'gold',
};

/** 活动状态图标 */
const statusIcons: Record<string, React.ReactNode> = {
  success: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  failed: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
  running: <SyncOutlined spin style={{ color: '#1677ff' }} />,
};

/** 格式化时间 */
function formatTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);

  if (diffMin < 1) return '刚刚';
  if (diffMin < 60) return `${diffMin} 分钟前`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr} 小时前`;
  if (diffHr < 168) return `${Math.floor(diffHr / 24)} 天前`;
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

const RecentActivityPanel: React.FC = () => {
  const [activities, setActivities] = useState<RecentActivity[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchActivities()
      .then((data) => { setActivities(data); setLoading(false); })
      .catch(() => { setLoading(false); });
  }, []);

  return (
    <Card
      loading={loading}
      title={
        <Title level={4} style={{ margin: 0 }}>
          最近活动
        </Title>
      }
      style={{ marginTop: 24 }}
    >
      {activities.length === 0 && !loading ? (
        <Text type="secondary">暂无活动记录</Text>
      ) : (
        <Timeline
          items={activities.map((act) => ({
            icon: activityIcons[act.type] || activityIcons.pipeline_run,
            content: (
              <div>
                <Space size={4} style={{ marginBottom: 4 }}>
                  <Tag
                    color={typeColors[act.type] || 'default'}
                    style={{ fontSize: 10, lineHeight: '16px', margin: 0 }}
                  >
                    {typeLabels[act.type] || act.type}
                  </Tag>
                  <Text strong>{act.title}</Text>
                  {act.status && (
                    <span style={{ fontSize: 12 }}>
                      {statusIcons[act.status]}
                    </span>
                  )}
                </Space>
                <div>
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    {act.description}
                  </Text>
                </div>
                <div style={{ marginTop: 4 }}>
                  <Space size={8}>
                    {act.agentName && (
                      <Tag color="blue" style={{ fontSize: 11 }}>
                        {act.agentName}
                      </Tag>
                    )}
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {formatTime(act.timestamp)}
                    </Text>
                  </Space>
                </div>
              </div>
            ),
          }))}
        />
      )}
    </Card>
  );
};

export default RecentActivityPanel;
