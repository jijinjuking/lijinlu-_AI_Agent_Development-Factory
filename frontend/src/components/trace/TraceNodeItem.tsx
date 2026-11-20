// ============================================================
// TraceNodeItem — Trace 树节点组件
// ============================================================

import React from 'react';
import { Typography, Space } from 'antd';
import {
  ThunderboltOutlined,
  ToolOutlined,
  LinkOutlined,
  RobotOutlined,
  UserOutlined,
  BugOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import type { TraceNode, TraceNodeType } from '../../types/trace';
import { TRACE_NODE_TYPE_COLORS } from '../../types/trace';

const { Text } = Typography;

/** 节点类型图标 */
const TYPE_ICONS: Record<TraceNodeType, React.ReactNode> = {
  llm_call: <ThunderboltOutlined />,
  tool_call: <ToolOutlined />,
  chain: <LinkOutlined />,
  agent_action: <RobotOutlined />,
  human_input: <UserOutlined />,
  error: <BugOutlined />,
};

/** 格式化耗时 */
function fmt(ms?: number): string {
  if (!ms) return '';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
}

interface TraceNodeItemProps {
  node: TraceNode;
  depth?: number;
  isSelected?: boolean;
  onSelect?: (nodeId: string) => void;
}

const TraceNodeItem: React.FC<TraceNodeItemProps> = ({
  node,
  depth = 0,
  isSelected = false,
  onSelect,
}) => {
  const color = TRACE_NODE_TYPE_COLORS[node.type] || '#8c8c8c';
  const isError = node.type === 'error' || node.status === 'failed';

  return (
    <div
      onClick={() => onSelect?.(node.id)}
      style={{
        padding: '6px 12px 6px 12px',
        paddingLeft: 12 + depth * 20,
        cursor: 'pointer',
        background: isSelected ? 'rgba(22,119,255,0.1)' : 'transparent',
        borderLeft: isSelected ? '3px solid #1677ff' : '3px solid transparent',
        transition: 'all 0.15s',
      }}
    >
      <Space size={6}>
        {/* 状态点 */}
        <span
          style={{
            display: 'inline-block',
            width: 8,
            height: 8,
            borderRadius: '50%',
            background:
              node.status === 'running'
                ? '#1677ff'
                : node.status === 'failed'
                  ? '#ff4d4f'
                  : node.status === 'success'
                    ? '#52c41a'
                    : '#8c8c8c',
            flexShrink: 0,
          }}
        />

        {/* 类型图标 */}
        <span style={{ color, fontSize: 13 }}>{TYPE_ICONS[node.type]}</span>

        {/* 名称 */}
        <Text
          style={{
            fontSize: 13,
            color: isError ? '#ff4d4f' : undefined,
            flex: 1,
          }}
          ellipsis={{ tooltip: node.name }}
        >
          {node.name}
        </Text>

        {/* 耗时 */}
        {node.duration !== undefined && (
          <Text type="secondary" style={{ fontSize: 11 }}>
            <ClockCircleOutlined style={{ marginRight: 2 }} />
            {fmt(node.duration)}
          </Text>
        )}

        {/* Token 消耗 */}
        {node.inputTokens !== undefined && (
          <Text type="secondary" style={{ fontSize: 11 }}>
            {(node.inputTokens + (node.outputTokens || 0) >= 1000)
              ? `${((node.inputTokens + (node.outputTokens || 0)) / 1000).toFixed(1)}k`
              : node.inputTokens + (node.outputTokens || 0)}
            {' tk'}
          </Text>
        )}
      </Space>
    </div>
  );
};

export default TraceNodeItem;
