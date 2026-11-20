// ============================================================
// ToolsPage — Tool Runtime 工具管理页面
// ============================================================

import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, Table, Button, Modal, Input, Select, Tag, Space, Descriptions,
  Tabs, App, Statistic, Row, Col, Badge, Typography, Tooltip,
} from 'antd';
import {
  ToolOutlined, PlayCircleOutlined, HistoryOutlined, AimOutlined,
  CheckCircleOutlined, CloseCircleOutlined, StopOutlined, ReloadOutlined,
  CodeOutlined, BranchesOutlined, ConsoleSqlOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  listTools, executeTool, listAuditLogs, getAuditStats, listTraces, getTraceStats,
  type ToolInfo, type AuditLogItem, type AuditStats, type TraceItem, type TraceStats,
} from '../api/tools';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

// 适配器图标映射
const adapterIcons: Record<string, React.ReactNode> = {
  shell: <ConsoleSqlOutlined />,
  git: <BranchesOutlined />,
  python: <CodeOutlined />,
};

const statusColors: Record<string, string> = {
  completed: 'green',
  failed: 'red',
  timeout: 'orange',
  denied: 'volcano',
  pending: 'blue',
  running: 'processing',
};

const ToolsPage: React.FC = () => {
  const { message } = App.useApp();
  // ── State ──
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(false);

  // 执行弹窗
  const [execModalOpen, setExecModalOpen] = useState(false);
  const [execTool, setExecTool] = useState<ToolInfo | null>(null);
  const [execArgs, setExecArgs] = useState('{}');
  const [execResult, setExecResult] = useState<string | null>(null);
  const [executing, setExecuting] = useState(false);

  // 审计
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>([]);
  const [auditStats, setAuditStats] = useState<AuditStats | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);

  // 追踪
  const [traces, setTraces] = useState<TraceItem[]>([]);
  const [traceStats, setTraceStats] = useState<TraceStats | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);

  // ── Load ──
  const loadTools = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listTools();
      setTools(data);
    } catch {
      message.error('加载工具列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadAudit = useCallback(async () => {
    setAuditLoading(true);
    try {
      const [logRes, stats] = await Promise.all([listAuditLogs({ limit: 100 }), getAuditStats()]);
      setAuditLogs(logRes.logs);
      setAuditStats(stats);
    } catch {
      message.error('加载审计日志失败');
    } finally {
      setAuditLoading(false);
    }
  }, []);

  const loadTraces = useCallback(async () => {
    setTraceLoading(true);
    try {
      const [traceRes, stats] = await Promise.all([listTraces({ limit: 100 }), getTraceStats()]);
      setTraces(traceRes.traces);
      setTraceStats(stats);
    } catch {
      message.error('加载追踪记录失败');
    } finally {
      setTraceLoading(false);
    }
  }, []);

  useEffect(() => { loadTools(); }, [loadTools]);

  // ── Execute ──
  const handleExecute = (tool: ToolInfo) => {
    setExecTool(tool);
    setExecArgs('{}');
    setExecResult(null);
    setExecModalOpen(true);
  };

  const handleExecSubmit = async () => {
    if (!execTool) return;
    setExecuting(true);
    try {
      const args = JSON.parse(execArgs);
      const result = await executeTool(execTool.name, { args });
      setExecResult(JSON.stringify(result, null, 2));
      if (result.status === 'completed') {
        message.success(`执行成功 (${result.duration_ms}ms)`);
      } else {
        message.warning(`执行结束: ${result.status}`);
      }
    } catch (e: unknown) {
      const err = e as Error;
      if (err.message?.includes('JSON')) {
        message.error('参数 JSON 格式错误');
      } else {
        message.error('执行失败: ' + (err.message || '未知错误'));
      }
      setExecResult(err.message || '执行异常');
    } finally {
      setExecuting(false);
    }
  };

  // ── Columns ──
  const toolColumns: ColumnsType<ToolInfo> = [
    {
      title: '工具名称', dataIndex: 'name', key: 'name', width: 160,
      render: (name: string, record) => (
        <Space>
          {adapterIcons[record.adapter_type] || <ToolOutlined />}
          <Text strong>{name}</Text>
        </Space>
      ),
    },
    { title: '显示名', dataIndex: 'display_name', key: 'display_name', width: 140 },
    {
      title: '描述', dataIndex: 'description', key: 'description', ellipsis: true,
      render: (v: string) => <Tooltip title={v}><Text type="secondary">{v || '-'}</Text></Tooltip>,
    },
    {
      title: '适配器', dataIndex: 'adapter_type', key: 'adapter_type', width: 80,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '权限', dataIndex: 'permission_level', key: 'permission_level', width: 80,
      render: (v: string) => {
        const colorMap: Record<string, string> = { readonly: 'green', normal: 'blue', elevated: 'orange', restricted: 'red' };
        return <Tag color={colorMap[v] || 'default'}>{v}</Tag>;
      },
    },
    { title: '超时', dataIndex: 'timeout_sec', key: 'timeout_sec', width: 60, render: (v: number) => `${v}s` },
    {
      title: '沙箱', dataIndex: 'sandbox_required', key: 'sandbox_required', width: 60,
      render: (v: boolean) => v ? <Tag color="orange">是</Tag> : <Tag>否</Tag>,
    },
    {
      title: '版本', dataIndex: 'version', key: 'version', width: 70,
    },
    {
      title: '操作', key: 'action', width: 80, fixed: 'right',
      render: (_, record) => (
        <Button type="primary" size="small" icon={<PlayCircleOutlined />} onClick={() => handleExecute(record)}>
          执行
        </Button>
      ),
    },
  ];

  const auditColumns: ColumnsType<AuditLogItem> = [
    { title: '工具', dataIndex: 'tool_name', key: 'tool_name', width: 120 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (v: string) => <Badge status={statusColors[v] as 'success' | 'error' | 'warning' | 'processing'} text={v} />,
    },
    { title: 'Task', dataIndex: 'task_id', key: 'task_id', width: 100, ellipsis: true },
    {
      title: '输出', dataIndex: 'output_result', key: 'output_result', ellipsis: true,
      render: (v: string | null) => v ? <Text code style={{ fontSize: 12 }}>{v.slice(0, 200)}</Text> : '-',
    },
    {
      title: '错误', dataIndex: 'output_error', key: 'output_error', ellipsis: true,
      render: (v: string | null) => v ? <Text type="danger" style={{ fontSize: 12 }}>{v.slice(0, 200)}</Text> : '-',
    },
    { title: '耗时', dataIndex: 'duration_ms', key: 'duration_ms', width: 80, render: (v: number) => `${v}ms` },
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 160, render: (v: string | null) => v ? new Date(v).toLocaleString() : '-' },
  ];

  const traceColumns: ColumnsType<TraceItem> = [
    { title: '工具', dataIndex: 'tool_name', key: 'tool_name', width: 120 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (v: string) => <Badge status={statusColors[v] as 'success' | 'error' | 'warning' | 'processing'} text={v} />,
    },
    { title: 'Task', dataIndex: 'task_id', key: 'task_id', width: 100, ellipsis: true },
    {
      title: '结果', dataIndex: 'result', key: 'result', ellipsis: true,
      render: (v: string | null) => v ? <Text code style={{ fontSize: 12 }}>{v.slice(0, 200)}</Text> : '-',
    },
    { title: '耗时', dataIndex: 'duration_ms', key: 'duration_ms', width: 80, render: (v: number) => `${v}ms` },
  ];

  // ── Tab Items ──
  const tabItems = [
    {
      key: 'tools',
      label: <span><ToolOutlined /> 工具列表</span>,
      children: (
        <Card extra={<Button icon={<ReloadOutlined />} onClick={loadTools} size="small">刷新</Button>}>
          <Table
            rowKey="name"
            columns={toolColumns}
            dataSource={tools}
            loading={loading}
            scroll={{ x: 1000 }}
            pagination={{ pageSize: 20 }}
            size="middle"
          />
        </Card>
      ),
    },
    {
      key: 'audit',
      label: <span><HistoryOutlined /> 审计日志</span>,
      children: (
        <div>
          {auditStats && (
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={6}><Card size="small"><Statistic title="总调用" value={auditStats.total} prefix={<HistoryOutlined />} /></Card></Col>
              <Col span={6}><Card size="small"><Statistic title="成功" value={auditStats.completed} styles={{ content: { color: '#3f8600' } }} prefix={<CheckCircleOutlined />} /></Card></Col>
              <Col span={6}><Card size="small"><Statistic title="失败" value={auditStats.failed} styles={{ content: { color: '#cf1322' } }} prefix={<CloseCircleOutlined />} /></Card></Col>
              <Col span={6}><Card size="small"><Statistic title="拒绝" value={auditStats.denied} styles={{ content: { color: '#d4380d' } }} prefix={<StopOutlined />} /></Card></Col>
            </Row>
          )}
          <Card extra={<Button icon={<ReloadOutlined />} onClick={loadAudit} size="small">刷新</Button>}>
            <Table
              rowKey="id"
              columns={auditColumns}
              dataSource={auditLogs}
              loading={auditLoading}
              scroll={{ x: 1000 }}
              pagination={{ pageSize: 20 }}
              size="small"
            />
          </Card>
        </div>
      ),
    },
    {
      key: 'traces',
      label: <span><AimOutlined /> 调用追踪</span>,
      children: (
        <div>
          {traceStats && (
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={6}><Card size="small"><Statistic title="总追踪" value={traceStats.total} prefix={<AimOutlined />} /></Card></Col>
              <Col span={6}><Card size="small"><Statistic title="成功" value={traceStats.completed} styles={{ content: { color: '#3f8600' } }} prefix={<CheckCircleOutlined />} /></Card></Col>
              <Col span={6}><Card size="small"><Statistic title="失败" value={traceStats.failed} styles={{ content: { color: '#cf1322' } }} prefix={<CloseCircleOutlined />} /></Card></Col>
              <Col span={6}><Card size="small"><Statistic title="拒绝" value={traceStats.denied} styles={{ content: { color: '#d4380d' } }} prefix={<StopOutlined />} /></Card></Col>
            </Row>
          )}
          <Card extra={<Button icon={<ReloadOutlined />} onClick={loadTraces} size="small">刷新</Button>}>
            <Table
              rowKey="trace_id"
              columns={traceColumns}
              dataSource={traces}
              loading={traceLoading}
              scroll={{ x: 800 }}
              pagination={{ pageSize: 20 }}
              size="small"
            />
          </Card>
        </div>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ margin: 0 }}><ToolOutlined /> Tool Runtime</h2>
          <Text type="secondary">统一工具注册、权限控制、执行追踪系统</Text>
        </div>
        <Text type="secondary">已注册: {tools.length} 个工具</Text>
      </div>

      <Tabs
        defaultActiveKey="tools"
        items={tabItems}
        onChange={(key) => {
          if (key === 'audit') loadAudit();
          if (key === 'traces') loadTraces();
        }}
      />

      {/* 执行弹窗 */}
      <Modal
        title={`执行工具: ${execTool?.name || ''}`}
        open={execModalOpen}
        onCancel={() => setExecModalOpen(false)}
        width={720}
        footer={[
          <Button key="cancel" onClick={() => setExecModalOpen(false)}>取消</Button>,
          <Button key="execute" type="primary" icon={<PlayCircleOutlined />} loading={executing} onClick={handleExecSubmit}>
            执行
          </Button>,
        ]}
      >
        {execTool && (
          <div>
            <Descriptions column={2} size="small" style={{ marginBottom: 12 }}>
              <Descriptions.Item label="工具名">{execTool.name}</Descriptions.Item>
              <Descriptions.Item label="适配器">
                <Tag icon={adapterIcons[execTool.adapter_type]}>{execTool.adapter_type}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="权限级别">
                <Tag>{execTool.permission_level}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="超时">{execTool.timeout_sec}s</Descriptions.Item>
              <Descriptions.Item label="描述" span={2}>{execTool.description}</Descriptions.Item>
            </Descriptions>

            <Text strong>参数 (JSON):</Text>
            <TextArea
              rows={6}
              value={execArgs}
              onChange={(e) => setExecArgs(e.target.value)}
              placeholder='{"command": "echo hello"}'
              style={{ marginTop: 8, fontFamily: 'monospace' }}
            />

            {execResult && (
              <div style={{ marginTop: 16 }}>
                <Text strong>执行结果:</Text>
                <pre style={{
                  background: '#f6f8fa', padding: 12, borderRadius: 6,
                  maxHeight: 300, overflow: 'auto', fontSize: 13,
                  border: '1px solid #e1e4e8', marginTop: 8,
                }}>
                  {execResult}
                </pre>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
};

export default ToolsPage;
