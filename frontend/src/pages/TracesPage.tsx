// ============================================================
// TracesPage — Trace 追踪页面
// ============================================================

import React, { useEffect } from 'react';
import { Typography, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useTraceStore } from '../stores/traceStore';
import TraceViewer from '../components/trace/TraceViewer';
import { TRACE_STATUS_LABELS } from '../types/trace';
import type { TraceStatus, TraceListItem } from '../types/trace';

const { Title, Text } = Typography;

/** 格式化耗时 */
function fmt(ms?: number): string {
  if (!ms) return '-';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(0)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
}

const columns: ColumnsType<TraceListItem> = [
  {
    title: '流程名称',
    dataIndex: 'pipelineName',
    key: 'pipelineName',
    width: 200,
    ellipsis: true,
  },
  {
    title: 'Agent',
    dataIndex: 'agentName',
    key: 'agentName',
    width: 130,
    render: (name: string) => <Tag color="blue">{name}</Tag>,
  },
  {
    title: '状态',
    dataIndex: 'status',
    key: 'status',
    width: 90,
    render: (status: TraceStatus) => (
      <Tag
        color={
          status === 'success' ? 'success' : status === 'failed' ? 'error' : 'processing'
        }
      >
        {TRACE_STATUS_LABELS[status]}
      </Tag>
    ),
  },
  {
    title: '耗时',
    dataIndex: 'duration',
    key: 'duration',
    width: 80,
    render: (v: number) => fmt(v),
  },
  {
    title: 'Tokens',
    dataIndex: 'totalTokens',
    key: 'totalTokens',
    width: 80,
    render: (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v),
  },
  {
    title: '费用',
    dataIndex: 'totalCost',
    key: 'totalCost',
    width: 80,
    render: (v: number) => `¥${v.toFixed(2)}`,
  },
];

const TracesPage: React.FC = () => {
  const { traceList, isLoading, loadTraceList, selectTrace, currentTrace } = useTraceStore();

  useEffect(() => {
    loadTraceList();
  }, [loadTraceList]);

  return (
    <div>
      <Title level={4} style={{ margin: '0 0 16px 0' }}>
        Trace 追踪
      </Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16, fontSize: 13 }}>
        查看每次 Agent 执行的完整链路，包括 LLM 调用、工具调用、耗时和费用
      </Text>

      <Table<TraceListItem>
        dataSource={traceList}
        columns={columns}
        rowKey="id"
        size="small"
        loading={isLoading}
        pagination={false}
        scroll={{ y: 200 }}
        onRow={(record) => ({
          onClick: () => selectTrace(record.id),
          style: {
            cursor: 'pointer',
            background: currentTrace?.id === record.id ? 'rgba(22,119,255,0.1)' : undefined,
          },
        })}
        style={{ marginBottom: 16 }}
      />

      {/* Trace 详情查看器 */}
      <div style={{ marginTop: 16 }}>
        <TraceViewer />
      </div>
    </div>
  );
};

export default TracesPage;
