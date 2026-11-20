// ============================================================
// TraceDetail — 选中节点详情面板
// ============================================================

import React from 'react';
import { Descriptions, Tag, Typography, Empty, Divider } from 'antd';
import { TRACE_NODE_TYPE_LABELS, TRACE_STATUS_LABELS } from '../../types/trace';
import type { TraceNode } from '../../types/trace';

const { Text, Paragraph } = Typography;

interface TraceDetailProps {
  node: TraceNode | undefined;
}

/** 格式化耗时 */
function fmt(ms?: number): string {
  if (!ms) return '-';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
}

const TraceDetail: React.FC<TraceDetailProps> = ({ node }) => {
  if (!node) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <Empty description="选择一个节点查看详情" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    );
  }

  return (
    <div style={{ padding: '12px 16px' }}>
      <Text strong style={{ fontSize: 15, display: 'block', marginBottom: 12 }}>
        {node.name}
      </Text>

      <Descriptions size="small" column={1} colon={false}>
        <Descriptions.Item label="类型">
          <Tag>{TRACE_NODE_TYPE_LABELS[node.type] || node.type}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag
            color={
              node.status === 'success'
                ? 'success'
                : node.status === 'failed'
                  ? 'error'
                  : node.status === 'running'
                    ? 'processing'
                    : 'default'
            }
          >
            {TRACE_STATUS_LABELS[node.status] || node.status}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="耗时">{fmt(node.duration)}</Descriptions.Item>

        {node.model && (
          <Descriptions.Item label="模型">{node.model}</Descriptions.Item>
        )}

        {node.toolName && (
          <Descriptions.Item label="工具">{node.toolName}</Descriptions.Item>
        )}

        {node.inputTokens !== undefined && (
          <Descriptions.Item label="Input Tokens">
            {node.inputTokens.toLocaleString()}
          </Descriptions.Item>
        )}

        {node.outputTokens !== undefined && (
          <Descriptions.Item label="Output Tokens">
            {node.outputTokens.toLocaleString()}
          </Descriptions.Item>
        )}

        {node.cost !== undefined && (
          <Descriptions.Item label="费用">
            &yen;{node.cost.toFixed(4)}
          </Descriptions.Item>
        )}
      </Descriptions>

      {node.error && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <Text type="danger" strong style={{ fontSize: 12 }}>
            Error
          </Text>
          <Paragraph
            type="danger"
            style={{ fontSize: 12, marginTop: 4, whiteSpace: 'pre-wrap' }}
          >
            {node.error}
          </Paragraph>
        </>
      )}

      {/* 输入 */}
      {node.input && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <Text type="secondary" strong style={{ fontSize: 12, display: 'block' }}>
            Input
          </Text>
          <Paragraph
            style={{
              fontSize: 12,
              marginTop: 4,
              maxHeight: 120,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              background: 'rgba(0,0,0,0.08)',
              padding: 8,
              borderRadius: 4,
            }}
            ellipsis={{ rows: 4, expandable: true, symbol: '展开' }}
          >
            {node.input}
          </Paragraph>
        </>
      )}

      {/* 输出 */}
      {node.output && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <Text type="secondary" strong style={{ fontSize: 12, display: 'block' }}>
            Output
          </Text>
          <Paragraph
            style={{
              fontSize: 12,
              marginTop: 4,
              maxHeight: 200,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              background: 'rgba(0,255,0,0.05)',
              padding: 8,
              borderRadius: 4,
            }}
            ellipsis={{ rows: 6, expandable: true, symbol: '展开' }}
          >
            {node.output}
          </Paragraph>
        </>
      )}
    </div>
  );
};

export default TraceDetail;
