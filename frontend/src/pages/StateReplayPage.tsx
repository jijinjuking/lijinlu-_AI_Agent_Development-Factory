// ============================================================
// pages/StateReplayPage.tsx — W20 State Replay 主页面
//
// 布局：
//   ┌──────────────────────────────────────────────────────┐
//   │  Header：任务选择                                     │
//   ├──────────────────────┬───────────────────────────────┤
//   │  左栏                 │  右栏                         │
//   │  Checkpoint 列表      │  State Snapshot 对比视图       │
//   │  （时间线风格）         │  当前选中 vs 上一个             │
//   └──────────────────────┴───────────────────────────────┘
//
// 功能：
//   - 加载任务所有 Checkpoint，按时间倒序展示
//   - 选中某个 Checkpoint 后，右侧展示完整 state_snapshot
//   - 当选中非首个 Checkpoint 时，右侧显示与前一个 Checkpoint 的 diff
//   - 一键「恢复到此 Checkpoint」
//   - 可删除指定 Checkpoint
// ============================================================

import React, { useState, useCallback, useMemo } from 'react';
import {
  Typography,
  Card,
  Input,
  Button,
  Alert,
  Empty,
  Spin,
  Table,
  Tag,
  Tooltip,
  Popconfirm,
  Space,
  Descriptions,
  Modal,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  HistoryOutlined,
  ReloadOutlined,
  DeleteOutlined,
  RollbackOutlined,
  SearchOutlined,
  DiffOutlined,
} from '@ant-design/icons';
import {
  listCheckpoints,
  getLatestCheckpoint,
  restoreCheckpoint,
  deleteCheckpoint,
  saveCheckpoint,
  getCheckpointDetail,
} from '../api/state';
import type { CheckpointItem, CheckpointDetail } from '../api/state';

const { Title, Text } = Typography;

// ──────────────────────────────────────────────────────────
// State Diff 视图（逐行对比两个快照）
// ──────────────────────────────────────────────────────────

function flattenObject(obj: Record<string, unknown>, prefix = ''): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [key, val] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (val !== null && typeof val === 'object' && !Array.isArray(val)) {
      Object.assign(result, flattenObject(val as Record<string, unknown>, fullKey));
    } else {
      result[fullKey] = JSON.stringify(val);
    }
  }
  return result;
}

interface StateDiffViewProps {
  baseSnapshot: Record<string, unknown> | null;
  targetSnapshot: Record<string, unknown>;
  baseLabel: string;
  targetLabel: string;
}

function StateDiffView({ baseSnapshot, targetSnapshot, baseLabel, targetLabel }: StateDiffViewProps) {
  const baseFlat = useMemo(
    () => (baseSnapshot ? flattenObject(baseSnapshot) : {}),
    [baseSnapshot],
  );
  const targetFlat = useMemo(() => flattenObject(targetSnapshot), [targetSnapshot]);

  const allKeys = useMemo(
    () => Array.from(new Set([...Object.keys(baseFlat), ...Object.keys(targetFlat)])).sort(),
    [baseFlat, targetFlat],
  );

  if (allKeys.length === 0) {
    return <Text type="secondary">快照为空</Text>;
  }

  return (
    <div style={{ fontFamily: 'monospace', fontSize: 12 }}>
      {/* 表头 */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '200px 1fr 1fr',
          gap: 8,
          padding: '4px 8px',
          background: '#f0f0f0',
          borderRadius: '4px 4px 0 0',
          fontWeight: 600,
          marginBottom: 2,
        }}
      >
        <span>字段</span>
        <span style={{ color: '#8c8c8c' }}>{baseLabel}</span>
        <span style={{ color: '#1677ff' }}>{targetLabel}</span>
      </div>
      {allKeys.map((key) => {
        const baseVal = baseFlat[key] ?? '—';
        const targetVal = targetFlat[key] ?? '—';
        const changed = baseVal !== targetVal;
        const isNew = !(key in baseFlat);
        const isRemoved = !(key in targetFlat);

        return (
          <div
            key={key}
            style={{
              display: 'grid',
              gridTemplateColumns: '200px 1fr 1fr',
              gap: 8,
              padding: '3px 8px',
              background: changed
                ? isNew
                  ? 'rgba(82, 196, 26, 0.08)'
                  : isRemoved
                  ? 'rgba(255, 77, 79, 0.08)'
                  : 'rgba(22, 119, 255, 0.06)'
                : 'transparent',
              borderLeft: changed ? `3px solid ${isNew ? '#52c41a' : isRemoved ? '#ff4d4f' : '#1677ff'}` : '3px solid transparent',
              marginBottom: 1,
            }}
          >
            <Text style={{ fontSize: 11, color: '#595959', wordBreak: 'break-all' }}>{key}</Text>
            <Text
              style={{
                fontSize: 11,
                color: isRemoved ? '#ff4d4f' : '#8c8c8c',
                textDecoration: isRemoved ? 'line-through' : 'none',
                wordBreak: 'break-all',
              }}
            >
              {baseVal}
            </Text>
            <Text
              style={{
                fontSize: 11,
                color: isNew ? '#52c41a' : changed ? '#1677ff' : '#595959',
                fontWeight: changed ? 600 : 400,
                wordBreak: 'break-all',
              }}
            >
              {targetVal}
            </Text>
          </div>
        );
      })}
    </div>
  );
}

// ──────────────────────────────────────────────────────────
// 主页面
// ──────────────────────────────────────────────────────────

const StateReplayPage: React.FC = () => {
  const [taskIdInput, setTaskIdInput] = useState('');
  const [currentTaskId, setCurrentTaskId] = useState('');
  const [checkpoints, setCheckpoints] = useState<CheckpointItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedCheckpointId, setSelectedCheckpointId] = useState<string | null>(null);
  const [checkpointDetail, setCheckpointDetail] = useState<CheckpointDetail | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [isRestoring, setIsRestoring] = useState(false);
  const [isDiffMode, setIsDiffMode] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();

  // 加载 Checkpoint 列表
  const handleLoadCheckpoints = useCallback(async (taskId?: string) => {
    const targetTaskId = taskId ?? taskIdInput.trim();
    if (!targetTaskId) return;

    setIsLoading(true);
    setLoadError(null);
    setCheckpoints([]);
    setSelectedCheckpointId(null);
    setCheckpointDetail(null);

    try {
      const resp = await listCheckpoints(targetTaskId);
      setCheckpoints(resp.checkpoints);
      setCurrentTaskId(targetTaskId);
    } catch (err: unknown) {
      setLoadError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setIsLoading(false);
    }
  }, [taskIdInput]);

  // 选中 Checkpoint，加载详情（含 state_snapshot）
  const handleSelectCheckpoint = useCallback(async (checkpointId: string) => {
    if (selectedCheckpointId === checkpointId) return;
    setSelectedCheckpointId(checkpointId);
    setIsLoadingDetail(true);

    try {
      const detail = await getCheckpointDetail(currentTaskId, checkpointId);
      setCheckpointDetail(detail);
    } catch {
      setCheckpointDetail(null);
    } finally {
      setIsLoadingDetail(false);
    }
  }, [selectedCheckpointId, currentTaskId]);

  // 一键恢复
  const handleRestore = useCallback(async (checkpointId: string) => {
    if (!currentTaskId) return;
    setIsRestoring(true);
    try {
      const result = await restoreCheckpoint(currentTaskId, checkpointId);
      messageApi.success('已恢复到该 Checkpoint');
      setCheckpointDetail({ ...result, id: checkpointId, event_seq_num: null } as unknown as CheckpointDetail);
      // 刷新列表
      await handleLoadCheckpoints(currentTaskId);
    } catch (err: unknown) {
      messageApi.error(err instanceof Error ? err.message : '恢复失败');
    } finally {
      setIsRestoring(false);
    }
  }, [currentTaskId, handleLoadCheckpoints, messageApi]);

  // 删除 Checkpoint
  const handleDelete = useCallback(async (checkpointId: string) => {
    if (!currentTaskId) return;
    try {
      await deleteCheckpoint(currentTaskId, checkpointId);
      messageApi.success('已删除');
      setCheckpoints((prev) => prev.filter((cp) => cp.id !== checkpointId));
      if (selectedCheckpointId === checkpointId) {
        setSelectedCheckpointId(null);
        setCheckpointDetail(null);
      }
    } catch (err: unknown) {
      messageApi.error(err instanceof Error ? err.message : '删除失败');
    }
  }, [currentTaskId, selectedCheckpointId, messageApi]);

  // 保存当前 Checkpoint
  const handleSaveCheckpoint = useCallback(async () => {
    if (!currentTaskId) return;
    try {
      await saveCheckpoint(currentTaskId);
      messageApi.success('Checkpoint 已保存');
      await handleLoadCheckpoints(currentTaskId);
    } catch (err: unknown) {
      messageApi.error(err instanceof Error ? err.message : '保存失败');
    }
  }, [currentTaskId, handleLoadCheckpoints, messageApi]);

  // 当前选中 Checkpoint 的索引（用于 diff）
  const selectedIndex = checkpoints.findIndex((cp) => cp.id === selectedCheckpointId);
  const prevCheckpoint = selectedIndex > 0 ? checkpoints[selectedIndex - 1] : null;
  const selectedCheckpoint = selectedIndex >= 0 ? checkpoints[selectedIndex] : null;

  // ── 表格列定义 ──
  const columns: ColumnsType<CheckpointItem> = [
    {
      title: '#',
      dataIndex: 'index',
      key: 'index',
      width: 44,
      render: (_: unknown, __: CheckpointItem, index: number) => (
        <Text type="secondary" style={{ fontSize: 11 }}>{checkpoints.length - index}</Text>
      ),
    },
    {
      title: '节点',
      dataIndex: 'node',
      key: 'node',
      width: 120,
      render: (node: string) => <Tag color="purple">{node || '—'}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'workflow_status',
      key: 'workflow_status',
      width: 90,
      render: (status: string) => {
        const colorMap: Record<string, string> = {
          running: 'processing',
          completed: 'success',
          failed: 'error',
          pending: 'default',
        };
        return <Tag color={colorMap[status] ?? 'default'}>{status || '—'}</Tag>;
      },
    },
    {
      title: '事件序号',
      dataIndex: 'event_seq_num',
      key: 'event_seq_num',
      width: 80,
      render: (seq: number | null) => (
        <Text style={{ fontSize: 11 }}>{seq ?? '—'}</Text>
      ),
    },
    {
      title: '保存时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (created: string | null) => (
        <Text style={{ fontSize: 11 }}>
          {created ? new Date(created).toLocaleString('zh-CN') : '—'}
        </Text>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_: unknown, record: CheckpointItem) => (
        <Space size={4}>
          <Tooltip title="恢复到此 Checkpoint">
            <Popconfirm
              title="确认恢复？"
              description={`将把任务状态回滚到此 Checkpoint，当前状态会被覆盖。`}
              onConfirm={() => handleRestore(record.id)}
              okText="确认恢复"
              cancelText="取消"
            >
              <Button
                size="small"
                icon={<RollbackOutlined />}
                loading={isRestoring}
                type="primary"
                ghost
              >
                恢复
              </Button>
            </Popconfirm>
          </Tooltip>
          <Tooltip title="删除">
            <Popconfirm
              title="确认删除？"
              onConfirm={() => handleDelete(record.id)}
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Button size="small" icon={<DeleteOutlined />} danger />
            </Popconfirm>
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: '20px 24px' }}>
      {contextHolder}

      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          <HistoryOutlined style={{ marginRight: 8, color: '#722ed1' }} />
          State 回放 / Checkpoint 管理
        </Title>
        <Text type="secondary" style={{ fontSize: 13 }}>
          查看任务的历史状态快照，支持对比差异与一键回滚
        </Text>
      </div>

      {/* 任务选择 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <Input.Search
            placeholder="输入 Task ID..."
            value={taskIdInput}
            onChange={(e) => setTaskIdInput(e.target.value)}
            onSearch={() => handleLoadCheckpoints()}
            enterButton={<><ReloadOutlined /> 加载</>}
            style={{ maxWidth: 460 }}
            loading={isLoading}
          />
          {currentTaskId && (
            <Button
              icon={<HistoryOutlined />}
              onClick={handleSaveCheckpoint}
              size="small"
            >
              保存当前快照
            </Button>
          )}
          {checkpoints.length > 0 && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              共 {checkpoints.length} 个 Checkpoint
            </Text>
          )}
        </div>
      </Card>

      {loadError && (
        <Alert type="error" message={loadError} closable style={{ marginBottom: 12 }} />
      )}

      {isLoading && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin size="large" tip="加载 Checkpoint 列表..." />
        </div>
      )}

      {!isLoading && checkpoints.length === 0 && currentTaskId && !loadError && (
        <Empty description={`任务 ${currentTaskId} 暂无 Checkpoint`} />
      )}

      {!isLoading && checkpoints.length === 0 && !currentTaskId && (
        <Empty description="输入 Task ID 并点击「加载」" />
      )}

      {/* 主内容区：列表 + 详情 */}
      {checkpoints.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {/* 左：Checkpoint 列表 */}
          <Card
            size="small"
            title={<><HistoryOutlined /> Checkpoint 历史</>}
            styles={{ body: { padding: 0 } }}
          >
            <Table
              dataSource={checkpoints}
              columns={columns}
              rowKey="id"
              size="small"
              pagination={false}
              rowClassName={(record) =>
                record.id === selectedCheckpointId ? 'ant-table-row-selected' : ''
              }
              onRow={(record) => ({
                onClick: () => handleSelectCheckpoint(record.id),
                style: { cursor: 'pointer' },
              })}
              scroll={{ y: 400 }}
            />
          </Card>

          {/* 右：State 快照 / Diff */}
          <Card
            size="small"
            title={
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <DiffOutlined />
                {selectedCheckpoint
                  ? `Checkpoint #${checkpoints.length - selectedIndex} 状态`
                  : '状态快照'}
                {selectedCheckpoint && prevCheckpoint && (
                  <Button
                    size="small"
                    type={isDiffMode ? 'primary' : 'default'}
                    onClick={() => setIsDiffMode(!isDiffMode)}
                    style={{ marginLeft: 8 }}
                  >
                    {isDiffMode ? '关闭对比' : '对比上一版'}
                  </Button>
                )}
              </div>
            }
            styles={{ body: { maxHeight: 460, overflow: 'auto' } }}
          >
            {isLoadingDetail && <Spin tip="加载详情..." />}

            {!selectedCheckpoint && (
              <Empty description="点击左侧 Checkpoint 行查看状态" imageStyle={{ height: 48 }} />
            )}

            {selectedCheckpoint && checkpointDetail && (
              isDiffMode && prevCheckpoint ? (
                <StateDiffView
                  baseSnapshot={null}
                  targetSnapshot={checkpointDetail.state_snapshot}
                  baseLabel={`上一个 CP`}
                  targetLabel={`当前选中 CP`}
                />
              ) : (
                <div style={{ fontFamily: 'monospace', fontSize: 12 }}>
                  {Object.entries(checkpointDetail.state_snapshot).map(([key, val]) => (
                    <div key={key} style={{ marginBottom: 4, display: 'flex', gap: 8 }}>
                      <Text strong style={{ color: '#8c8c8c', minWidth: 140 }}>{key}:</Text>
                      <Text style={{ color: '#595959', wordBreak: 'break-all' }}>
                        {JSON.stringify(val)}
                      </Text>
                    </div>
                  ))}
                </div>
              )
            )}

            {selectedCheckpoint && !checkpointDetail && (
              <div style={{ padding: 8 }}>
                <Descriptions size="small" column={1} bordered>
                  <Descriptions.Item label="Checkpoint ID">
                    <Text copyable style={{ fontSize: 11, fontFamily: 'monospace' }}>
                      {selectedCheckpoint.id}
                    </Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="所在节点">
                    <Tag color="purple">{selectedCheckpoint.node || '—'}</Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="工作流状态">
                    {selectedCheckpoint.workflow_status || '—'}
                  </Descriptions.Item>
                  <Descriptions.Item label="事件序号">
                    {selectedCheckpoint.event_seq_num ?? '—'}
                  </Descriptions.Item>
                  <Descriptions.Item label="保存时间">
                    {selectedCheckpoint.created_at
                      ? new Date(selectedCheckpoint.created_at).toLocaleString('zh-CN')
                      : '—'}
                  </Descriptions.Item>
                </Descriptions>
                <Alert
                  type="info"
                  message="点击「恢复」以加载完整 State Snapshot"
                  style={{ marginTop: 12 }}
                  showIcon
                />
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
};

export default StateReplayPage;
