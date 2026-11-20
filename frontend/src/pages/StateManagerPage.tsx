// ============================================================
// StateManagerPage — State 与 Checkpoint 可视化管理页面
// W3 Phase 1: State 查看 / Checkpoint 时间线 / 恢复操作
// ============================================================

import React, { useState, useCallback } from 'react';
import {
  Card, Input, Button, Table, Tag, Space, Typography,
  Descriptions, Alert, Popconfirm, App, Spin, Empty, Tabs, Timeline, Tooltip,
} from 'antd';
import {
  SearchOutlined, HistoryOutlined, UndoOutlined,
  SaveOutlined, DeleteOutlined, FileProtectOutlined, WarningOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  getState, getStateSize, listCheckpoints, saveCheckpoint,
  restoreCheckpoint, deleteCheckpoint, initializeState,
  type StateInfo, type CheckpointItem, type StateSizeInfo,
} from '../api/state';
import { fetchAgents } from '../api/agents';
import { fetchTasks, type Task } from '../api/tasks';

const { Title, Text, Paragraph } = Typography;
const { TabPane } = Tabs;

// ── 颜色映射 ──
const STATUS_COLORS: Record<string, string> = {
  idle: 'default',
  running: 'processing',
  completed: 'success',
  failed: 'error',
  paused: 'warning',
  waiting_approval: 'purple',
  cancelled: 'default',
};

const StateManagerPage: React.FC = () => {
  const { message } = App.useApp();
  const [taskId, setTaskId] = useState('');
  const [loading, setLoading] = useState(false);
  const [state, setState] = useState<StateInfo | null>(null);
  const [sizeInfo, setSizeInfo] = useState<StateSizeInfo | null>(null);
  const [checkpoints, setCheckpoints] = useState<CheckpointItem[]>([]);
  const [searchResult, setSearchResult] = useState<Task[]>([]);
  const [searching, setSearching] = useState(false);

  // ── 搜索任务 ──
  const handleSearch = useCallback(async () => {
    if (!taskId.trim()) {
      message.warning('请输入 Task ID');
      return;
    }
    setLoading(true);
    try {
      const data = await getState(taskId.trim());
      setState(data);
      // 同时加载 Size 和 Checkpoints
      const [sz, cps] = await Promise.all([
        getStateSize(taskId.trim()).catch(() => null),
        listCheckpoints(taskId.trim()).catch(() => ({ checkpoints: [], count: 0, task_id: taskId })),
      ]);
      setSizeInfo(sz);
      setCheckpoints(cps.checkpoints);
    } catch {
      message.error('State 未找到，可尝试初始化');
      setState(null);
      setSizeInfo(null);
      setCheckpoints([]);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  const handleInit = useCallback(async () => {
    if (!taskId.trim()) return;
    setLoading(true);
    try {
      const data = await initializeState(taskId.trim(), '');
      setState(data);
      message.success('State 初始化成功');
    } catch (e: unknown) {
      message.error('初始化失败: ' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  const handleSaveCheckpoint = useCallback(async () => {
    if (!taskId.trim()) return;
    setLoading(true);
    try {
      await saveCheckpoint(taskId.trim());
      message.success('Checkpoint 已保存');
      const cps = await listCheckpoints(taskId.trim());
      setCheckpoints(cps.checkpoints);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  const handleRestore = useCallback(async (cpId: string) => {
    if (!taskId.trim()) return;
    setLoading(true);
    try {
      const result = await restoreCheckpoint(taskId.trim(), cpId);
      setState(result);
      message.success('State 已恢复');
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  const handleDeleteCheckpoint = useCallback(async (cpId: string) => {
    if (!taskId.trim()) return;
    try {
      await deleteCheckpoint(taskId.trim(), cpId);
      message.success('Checkpoint 已删除');
      setCheckpoints(prev => prev.filter(c => c.id !== cpId));
    } catch {
      message.error('删除失败');
    }
  }, [taskId]);

  // ── Checkpoint 表格列 ──
  const cpColumns: ColumnsType<CheckpointItem> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 200,
      render: (v: string | null) => v ? new Date(v).toLocaleString() : '-',
    },
    {
      title: '节点',
      dataIndex: 'node',
      width: 140,
      render: (v: string) => v || <Text type="secondary">—</Text>,
    },
    {
      title: '状态',
      dataIndex: 'workflow_status',
      width: 100,
      render: (s: string) => (
        <Tag color={STATUS_COLORS[s] || 'default'}>{s || '未知'}</Tag>
      ),
    },
    {
      title: '大小',
      dataIndex: 'state_size',
      width: 80,
      render: (v: number) => `${(v / 1024).toFixed(1)} KB`,
    },
    {
      title: '操作',
      width: 180,
      render: (_, record) => (
        <Space size="small">
          <Tooltip title="从此 Checkpoint 恢复 State">
            <Button
              size="small"
              icon={<UndoOutlined />}
              onClick={() => handleRestore(record.id)}
            >
              恢复
            </Button>
          </Tooltip>
          <Popconfirm
            title="确定删除此 Checkpoint？"
            onConfirm={() => handleDeleteCheckpoint(record.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // ── State 关键字段展示 ──
  const stateData = state?.state || {};

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <Title level={4}>
        <FileProtectOutlined /> State Manager
        <Text type="secondary" style={{ fontSize: 14, marginLeft: 12 }}>
          Phase 1 W3 — 轻量 State + Checkpoint 管理
        </Text>
      </Title>

      {/* ── 搜索栏 ── */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space>
          <Input.Search
            placeholder="输入 Task ID"
            value={taskId}
            onChange={(e) => setTaskId(e.target.value)}
            onSearch={handleSearch}
            enterButton={<><SearchOutlined /> 查询</>}
            style={{ width: 400 }}
            loading={loading}
          />
          <Button onClick={handleInit} disabled={!taskId.trim()}>
            初始化 State
          </Button>
          <Button
            icon={<SaveOutlined />}
            onClick={handleSaveCheckpoint}
            disabled={!state}
          >
            保存 Checkpoint
          </Button>
        </Space>
      </Card>

      {loading ? (
        <Spin description="加载中..." style={{ display: 'block', margin: '40px auto' }} />
      ) : !state ? (
        <Empty description="输入 Task ID 查询 State" style={{ marginTop: 60 }} />
      ) : (
        <Tabs defaultActiveKey="state">
          {/* ── State 详情 ── */}
          <TabPane tab="State 详情" key="state">
            {/* 大小警告 */}
            {sizeInfo && !sizeInfo.ok && (
              <Alert
                type="error"
                message={`State 大小 ${(sizeInfo.size_bytes / 1024).toFixed(1)} KB，超过 ${(sizeInfo.limit_bytes / 1024).toFixed(0)} KB 限制！`}
                description="请将大内容移到 Artifact Store，State 只保留 artifact_refs 引用。"
                showIcon
                style={{ marginBottom: 16 }}
              />
            )}
            {sizeInfo && sizeInfo.percent > 10 && sizeInfo.ok && (
              <Alert
                type="warning"
                message={`State 大小 ${(sizeInfo.size_bytes / 1024).toFixed(1)} KB（${sizeInfo.percent}%），建议关注`}
                showIcon
                icon={<WarningOutlined />}
                style={{ marginBottom: 16 }}
              />
            )}

            {/* 提示信息 */}
            {state.warnings && state.warnings.length > 0 && (
              <Card size="small" style={{ marginBottom: 16 }}>
                {state.warnings.map((w, i) => (
                  <Alert
                    key={i}
                    type="warning"
                    message={`[${w.field}] ${w.message}`}
                    showIcon
                    style={{ marginBottom: 4 }}
                  />
                ))}
              </Card>
            )}

            {/* 核心字段 */}
            <Card title="流程控制" size="small" style={{ marginBottom: 16 }}>
              <Descriptions column={3} size="small">
                <Descriptions.Item label="当前节点">
                  <Tag>{String(stateData.current_node || '—')}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="工作流状态">
                  <Tag color={STATUS_COLORS[String(stateData.workflow_status || 'idle')]}>
                    {String(stateData.workflow_status || 'idle')}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="错误计数">
                  {String(stateData.error_count || 0)} / {String(stateData.max_retries || 3)}
                </Descriptions.Item>
                <Descriptions.Item label="当前目标">
                  {String(stateData.current_goal || '—')}
                </Descriptions.Item>
                <Descriptions.Item label="项目 ID">
                  {String(stateData.project_id || '—')}
                </Descriptions.Item>
              </Descriptions>
            </Card>

            {/* 引用 */}
            <Card title="引用计数" size="small" style={{ marginBottom: 16 }}>
              <Descriptions column={2} size="small">
                <Descriptions.Item label="Artifact 引用数">
                  {Array.isArray(stateData.artifact_refs) ? (stateData.artifact_refs as unknown[]).length : 0}
                </Descriptions.Item>
                <Descriptions.Item label="Context 引用数">
                  {Array.isArray(stateData.context_refs) ? (stateData.context_refs as unknown[]).length : 0}
                </Descriptions.Item>
                <Descriptions.Item label="消息数">
                  {Array.isArray(stateData.messages) ? (stateData.messages as unknown[]).length : 0}
                </Descriptions.Item>
                <Descriptions.Item label="步骤数">
                  {Array.isArray(stateData.steps) ? (stateData.steps as unknown[]).length : 0}
                </Descriptions.Item>
              </Descriptions>
            </Card>

            {/* 审批状态 */}
            <Card title="人工干预" size="small" style={{ marginBottom: 16 }}>
              <Descriptions column={2} size="small">
                <Descriptions.Item label="需要审批">
                  {stateData.approval_needed ? <Tag color="orange">是</Tag> : <Tag>否</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="审批结果">
                  {stateData.approval_result === null || stateData.approval_result === undefined
                    ? '—'
                    : stateData.approval_result
                      ? <Tag color="success">通过</Tag>
                      : <Tag color="error">拒绝</Tag>
                  }
                </Descriptions.Item>
              </Descriptions>
            </Card>

            {/* 元数据 */}
            <Card title="元数据" size="small" style={{ marginBottom: 16 }}>
              <Descriptions column={2} size="small">
                {stateData.metadata && typeof stateData.metadata === 'object'
                  ? Object.entries(stateData.metadata as Record<string, unknown>).map(([k, v]) => (
                    <Descriptions.Item key={k} label={k}>
                      {typeof v === 'number' ? v.toLocaleString() : String(v)}
                    </Descriptions.Item>
                  ))
                  : <Descriptions.Item label="—">—</Descriptions.Item>
                }
              </Descriptions>
            </Card>

            {/* 原始 JSON */}
            <Card
              title={`State 原始数据（${state.size_bytes} bytes）`}
              size="small"
            >
              <pre style={{
                background: '#f6f8fa',
                padding: 16,
                borderRadius: 6,
                fontSize: 12,
                maxHeight: 400,
                overflow: 'auto',
              }}>
                {JSON.stringify(stateData, null, 2)}
              </pre>
            </Card>
          </TabPane>

          {/* ── Checkpoint 时间线 ── */}
          <TabPane
            tab={<><HistoryOutlined /> Checkpoints ({checkpoints.length})</>}
            key="checkpoints"
          >
            <div style={{ display: 'flex', gap: 16 }}>
              {/* 左侧表格 */}
              <div style={{ flex: 1 }}>
                <Table
                  columns={cpColumns}
                  dataSource={checkpoints}
                  rowKey="id"
                  size="small"
                  pagination={{ pageSize: 10 }}
                  locale={{ emptyText: '暂无 Checkpoint' }}
                />
              </div>

              {/* 右侧时间线 */}
              <div style={{ width: 280 }}>
                <Card title="时间线" size="small">
                  <Timeline
                    items={[...checkpoints].reverse().map(cp => ({
                      color: cp.workflow_status === 'failed' ? 'red'
                            : cp.workflow_status === 'completed' ? 'green'
                            : 'blue',
                      children: (
                        <div>
                          <div style={{ fontWeight: 600, fontSize: 13 }}>
                            {cp.node || 'unknown'}
                          </div>
                          <Tag color={STATUS_COLORS[cp.workflow_status] || 'default'} style={{ fontSize: 11 }}>
                            {cp.workflow_status || 'unknown'}
                          </Tag>
                          <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>
                            {cp.created_at ? new Date(cp.created_at).toLocaleTimeString() : '—'}
                          </div>
                        </div>
                      ),
                    }))}
                  />
                </Card>
              </div>
            </div>
          </TabPane>
        </Tabs>
      )}
    </div>
  );
};

export default StateManagerPage;
