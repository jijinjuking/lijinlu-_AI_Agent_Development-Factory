// ============================================================
// ArtifactsPage — Artifact 产物管理（含 W23-24 版本管理）
// ============================================================

import React, { useEffect, useState, useCallback } from 'react';
import {
  Table, Card, Tag, Space, Button, Typography, Modal, Descriptions,
  App, Select, Popconfirm, Spin, Empty, Tabs,
} from 'antd';
import {
  DeleteOutlined, EyeOutlined, FileTextOutlined, ReloadOutlined,
  HistoryOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  listArtifacts, getArtifactContent, deleteArtifact,
  type ArtifactMeta,
} from '../api/artifacts';
import ArtifactVersionPanel from '../components/artifacts/ArtifactVersionPanel';

const { Text } = Typography;

const ARTIFACT_TYPE_MAP: Record<string, { label: string; color: string }> = {
  requirement_doc: { label: '需求文档', color: 'blue' },
  architecture_doc: { label: '架构设计', color: 'purple' },
  code_file: { label: '代码文件', color: 'green' },
  code_patch: { label: '代码补丁', color: 'orange' },
  test_result: { label: '测试结果', color: 'cyan' },
  review_report: { label: '审查报告', color: 'gold' },
  deploy_log: { label: '部署日志', color: 'lime' },
  browser_screenshot: { label: '浏览器截图', color: 'pink' },
  runtime_trace: { label: '运行时追踪', color: 'red' },
  context_snapshot: { label: '上下文快照', color: 'geekblue' },
};

const ArtifactsPage: React.FC = () => {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [artifacts, setArtifacts] = useState<ArtifactMeta[]>([]);
  const [total, setTotal] = useState(0);
  const [typeFilter, setTypeFilter] = useState<string>();

  // 详情弹窗
  const [detailModal, setDetailModal] = useState(false);
  const [selectedMeta, setSelectedMeta] = useState<ArtifactMeta | null>(null);
  const [content, setContent] = useState('');
  const [contentLoading, setContentLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('content');

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listArtifacts({ limit: 100 });
      setArtifacts(res.artifacts);
      setTotal(res.count);
    } catch {
      message.error('加载 Artifact 列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchList(); }, [fetchList]);

  const showDetail = async (record: ArtifactMeta) => {
    setSelectedMeta(record);
    setDetailModal(true);
    setActiveTab('content');
    setContentLoading(true);
    try {
      const text = await getArtifactContent(record.id);
      setContent(text);
    } catch {
      setContent('（加载内容失败）');
    } finally {
      setContentLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteArtifact(id);
      message.success('已删除');
      fetchList();
    } catch {
      message.error('删除失败');
    }
  };

  const handleRollbackComplete = useCallback((newId: string) => {
    message.success(`回滚成功，新版本 ID: ${newId.slice(0, 8)}...`);
    fetchList();
    // 更新当前选中的 artifact（用新版本）
    setSelectedMeta((prev) => prev ? { ...prev, id: newId } : null);
  }, [fetchList, message]);

  const filtered = typeFilter
    ? artifacts.filter((a) => a.artifact_type === typeFilter)
    : artifacts;

  const columns: ColumnsType<ArtifactMeta> = [
    {
      title: '类型',
      dataIndex: 'artifact_type',
      width: 120,
      render: (t: string) => {
        const info = ARTIFACT_TYPE_MAP[t] || { label: t, color: 'default' };
        return <Tag color={info.color}>{info.label}</Tag>;
      },
    },
    {
      title: 'ID',
      dataIndex: 'id',
      ellipsis: true,
      width: 120,
      render: (id: string) => (
        <Text copyable style={{ fontSize: 12 }}>{id.slice(0, 8)}</Text>
      ),
    },
    {
      title: '关联任务',
      dataIndex: 'task_id',
      width: 120,
      ellipsis: true,
      render: (tid: string | null) =>
        tid ? <Text copyable style={{ fontSize: 12 }}>{tid.slice(0, 8)}</Text> : '-',
    },
    {
      title: '创建者',
      dataIndex: 'created_by_agent',
      width: 100,
      ellipsis: true,
      render: (v: string | null) => v || '-',
    },
    {
      title: '版本',
      dataIndex: 'version',
      width: 56,
      render: (v: number) => <Tag color="blue">v{v}</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 160,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      width: 150,
      render: (_, record) => (
        <Space size="small">
          <Button size="small" icon={<EyeOutlined />} onClick={() => showDetail(record)}>
            查看
          </Button>
          <Button
            size="small"
            icon={<HistoryOutlined />}
            onClick={() => {
              setSelectedMeta(record);
              setDetailModal(true);
              setActiveTab('versions');
            }}
          >
            版本
          </Button>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const typeOptions = Object.entries(ARTIFACT_TYPE_MAP).map(([k, v]) => ({
    value: k,
    label: v.label,
  }));

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <Space>
            <FileTextOutlined />
            <span>Artifact 产物管理</span>
            <Tag>{total} 个</Tag>
          </Space>
        }
        extra={
          <Space>
            <Select
              allowClear
              placeholder="按类型筛选"
              style={{ width: 140 }}
              options={typeOptions}
              value={typeFilter}
              onChange={(v) => setTypeFilter(v)}
            />
            <Button icon={<ReloadOutlined />} onClick={fetchList}>刷新</Button>
          </Space>
        }
      >
        <Table
          columns={columns}
          dataSource={filtered}
          rowKey="id"
          loading={loading}
          size="middle"
          locale={{ emptyText: <Empty description="暂无 Artifact" /> }}
          pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
        />
      </Card>

      {/* 详情 + 版本管理弹窗 */}
      <Modal
        title={
          selectedMeta ? (
            <Space>
              <FileTextOutlined />
              <span>Artifact 详情</span>
              <Tag color={ARTIFACT_TYPE_MAP[selectedMeta.artifact_type]?.color ?? 'default'}>
                {ARTIFACT_TYPE_MAP[selectedMeta.artifact_type]?.label ?? selectedMeta.artifact_type}
              </Tag>
              <Tag color="blue">v{selectedMeta.version}</Tag>
            </Space>
          ) : 'Artifact 详情'
        }
        open={detailModal}
        onCancel={() => { setDetailModal(false); setContent(''); }}
        width={860}
        footer={null}
        destroyOnHidden
      >
        {selectedMeta && (
          <>
            <Descriptions column={2} size="small" bordered style={{ marginBottom: 12 }}>
              <Descriptions.Item label="ID">
                <Text copyable style={{ fontSize: 11 }}>{selectedMeta.id}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="任务">{selectedMeta.task_id?.slice(0, 8) || '-'}</Descriptions.Item>
              <Descriptions.Item label="创建者">{selectedMeta.created_by_agent || '-'}</Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {selectedMeta.created_at ? new Date(selectedMeta.created_at).toLocaleString('zh-CN') : '-'}
              </Descriptions.Item>
            </Descriptions>

            <Tabs
              activeKey={activeTab}
              onChange={setActiveTab}
              items={[
                {
                  key: 'content',
                  label: '内容预览',
                  children: contentLoading ? (
                    <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
                  ) : (
                    <pre style={{
                      maxHeight: 420,
                      overflow: 'auto',
                      background: '#1e1e1e',
                      color: '#d4d4d4',
                      padding: 16,
                      borderRadius: 8,
                      fontSize: 13,
                      lineHeight: 1.6,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                    }}>
                      {content || '(空)'}
                    </pre>
                  ),
                },
                {
                  key: 'versions',
                  label: <><HistoryOutlined /> 版本管理</>,
                  children: (
                    <ArtifactVersionPanel
                      artifactId={selectedMeta.id}
                      onRollbackComplete={handleRollbackComplete}
                    />
                  ),
                },
              ]}
            />
          </>
        )}
      </Modal>
    </div>
  );
};

export default ArtifactsPage;
