// ============================================================
// MemoryPage — 记忆管理（真实 API）
// ============================================================

import React from 'react';
import { useState, useMemo, useEffect } from 'react';
import {
  Typography, Card, Tabs, Table, Tag, Space, Input,
  Select, Row, Col, Statistic, Tooltip, Button, Spin,
  Form, Modal, Drawer, Popconfirm, InputNumber, App,
} from 'antd';
import {
  DatabaseOutlined, CloudOutlined, UserOutlined, ProjectOutlined,
  SearchOutlined, DeleteOutlined, EditOutlined, EyeOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { fetchMemories, fetchMemoryStats, createMemory, deleteMemory } from '../api/memory';
import type { MemoryEntry } from '../types/memory';

const { Title, Text, Paragraph } = Typography;
const { Search } = Input;

const layerIcons: Record<string, React.ReactNode> = {
  cloud: <CloudOutlined />,
  user: <UserOutlined />,
  project: <ProjectOutlined />,
};

const LAYER_LABELS: Record<string, { label: string; color: string }> = {
  cloud: { label: '云端记忆', color: '#1677ff' },
  user: { label: '用户记忆', color: '#52c41a' },
  project: { label: '项目记忆', color: '#fa8c16' },
};

function importanceLabel(val: number): { text: string; color: string } {
  if (val >= 7) return { text: '高', color: '#ff4d4f' };
  if (val >= 4) return { text: '中', color: '#faad14' };
  return { text: '低', color: '#8c8c8c' };
}

const MemoryPage: React.FC = () => {
  const { message } = App.useApp();
  const [activeLayer, setActiveLayer] = useState<"cloud" | "user" | "project">('cloud');
  const [searchText, setSearchText] = useState('');
  const [importanceFilter, setImportanceFilter] = useState<string>('all');

  // 编辑/新建 Memory 的 Modal 状态
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingMemory, setEditingMemory] = useState<MemoryEntry | null>(null);
  const [editForm] = Form.useForm();

  // 查看详情的 Drawer 状态
  const [viewDrawerOpen, setViewDrawerOpen] = useState(false);
  const [viewingMemory, setViewingMemory] = useState<MemoryEntry | null>(null);

  // API
  const [allMemories, setAllMemories] = useState<MemoryEntry[]>([]);
  const [layerCounts, setLayerCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([fetchMemories(), fetchMemoryStats()])
      .then(([memories, stats]) => {
        setAllMemories(memories);
        setLayerCounts(stats);
      })
      .catch((e) => message.error(`加载记忆失败: ${e?.message || '未知错误'}`))
      .finally(() => setLoading(false));
  }, []);

  const filteredMemories = useMemo(() => {
    return allMemories.filter((m) => {
      if (m.layer !== activeLayer) return false;
      const matchSearch = !searchText
        || m.content.includes(searchText)
        || m.tags.some((t) => t.includes(searchText))
        || (m.source || '').includes(searchText);
      const matchImportance = importanceFilter === 'all'
        || (importanceFilter === 'high' && m.importance >= 7)
        || (importanceFilter === 'medium' && m.importance >= 4 && m.importance < 7)
        || (importanceFilter === 'low' && m.importance < 4);
      return matchSearch && matchImportance;
    });
  }, [allMemories, activeLayer, searchText, importanceFilter]);

  const layerEntries = useMemo(() => allMemories.filter((m) => m.layer === activeLayer), [allMemories, activeLayer]);
  const layerStats = useMemo(() => {
    const highCount = layerEntries.filter((m) => m.importance >= 7).length;
    return { count: layerEntries.length, highCount };
  }, [layerEntries]);

  // 查看记忆详情
  const handleView = (record: MemoryEntry) => {
    setViewingMemory(record);
    setViewDrawerOpen(true);
  };

  // 编辑记忆
  const handleEdit = (record: MemoryEntry) => {
    setEditingMemory(record);
    editForm.setFieldsValue({
      content: record.content,
      importance: record.importance,
      tags: record.tags.join(', '),
    });
    setEditModalOpen(true);
  };

  // 删除记忆
  const handleDelete = async (record: MemoryEntry) => {
    try {
      await deleteMemory(record.id);
      message.success('删除成功');
      // 刷新列表
      setLoading(true);
      Promise.all([fetchMemories(), fetchMemoryStats()])
        .then(([memories, stats]) => {
          setAllMemories(memories);
          setLayerCounts(stats);
        })
        .catch(() => message.error('刷新列表失败'))
        .finally(() => setLoading(false));
    } catch (e: any) {
      message.error(`删除失败: ${e?.message || '未知错误'}`);
    }
  };

  // 保存编辑/新建
  const handleSave = async (values: any) => {
    try {
      const tags = (values.tags || '').split(',').map((t: string) => t.trim()).filter(Boolean);
      if (editingMemory) {
        // TODO: 实现 updateMemory API
        message.warning('编辑功能即将上线');
        // await updateMemory(editingMemory.id, {
        //   content: values.content,
        //   importance: values.importance,
        //   tags,
        // });
        // message.success('更新成功');
      } else {
        await createMemory({
          layer: activeLayer,
          content: values.content,
          importance: values.importance,
          tags,
          source: 'user',
        });
        message.success('创建成功');
      }
      setEditModalOpen(false);
      setEditingMemory(null);
      // 刷新列表
      setLoading(true);
      Promise.all([fetchMemories(), fetchMemoryStats()])
        .then(([memories, stats]) => {
          setAllMemories(memories);
          setLayerCounts(stats);
        })
        .catch(() => message.error('刷新列表失败'))
        .finally(() => setLoading(false));
    } catch (e: any) {
      message.error(`保存失败: ${e?.message || '未知错误'}`);
    }
  };

  const columns: ColumnsType<MemoryEntry> = [
    {
      title: '内容', key: 'content', width: 400,
      render: (_, record) => (
        <div>
          <Tooltip title={record.content}>
            <Text ellipsis style={{ maxWidth: 380, display: 'inline-block' }}>{record.content}</Text>
          </Tooltip>
          <div style={{ marginTop: 2 }}>
            {record.tags.map((t) => <Tag key={t} style={{ fontSize: 11 }}>{t}</Tag>)}
          </div>
        </div>
      ),
    },
    {
      title: '重要性', dataIndex: 'importance', key: 'importance', width: 80,
      render: (v: number) => {
        const { text, color } = importanceLabel(v);
        return <Tag color={color}>{text}</Tag>;
      },
    },
    {
      title: '来源', dataIndex: 'source', key: 'source', width: 90,
      render: (v: string) => v || '-',
    },
    {
      title: '更新时间', dataIndex: 'updated_at', key: 'time', width: 110,
      render: (v: string) => v ? new Date(v).toLocaleDateString() : '-',
    },
    {
      title: '操作', key: 'actions', width: 100, fixed: 'right' as const,
      render: (_, record) => (
        <Space size="small">
          <Tooltip title="查看"><Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleView(record)} /></Tooltip>
          <Tooltip title="编辑"><Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)} /></Tooltip>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record)}>
            <Tooltip title="删除"><Button type="link" size="small" danger icon={<DeleteOutlined />} /></Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const tabItems = Object.entries(LAYER_LABELS).map(([key, { label, color }]) => ({
    key,
    label: (
      <Space>
        {layerIcons[key]}
        <span>{label}</span>
        <Tag color={color} style={{ marginLeft: 4 }}>
          {layerCounts[key] ?? allMemories.filter((m) => m.layer === key).length}
        </Tag>
      </Space>
    ),
  }));

  if (loading) {
    return (
      <div>
        <Title level={4}>记忆管理</Title>
        <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>记忆管理</Title>
        <Text type="secondary">查看和管理 AI Agent 的三层记忆系统</Text>
      </div>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic title={`${LAYER_LABELS[activeLayer]?.label || activeLayer}条目`}
              value={layerStats.count} suffix="条"
              prefix={<DatabaseOutlined style={{ color: LAYER_LABELS[activeLayer]?.color || '#1677ff' }} />} />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic title="高优先级" value={layerStats.highCount} suffix="条"
              prefix={<ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />} />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic title="总条目" value={allMemories.length} suffix="条"
              prefix={<CloudOutlined style={{ color: '#1677ff' }} />} />
          </Card>
        </Col>
      </Row>

      <Card>
        <Tabs activeKey={activeLayer} onChange={(k) => { setActiveLayer(k as "cloud" | "user" | "project"); setSearchText(''); }}
          items={tabItems} />

        <Space wrap style={{ marginBottom: 16 }}>
          <Search placeholder="搜索记忆..." allowClear style={{ width: 280 }}
            prefix={<SearchOutlined />}
            onSearch={setSearchText} onChange={(e) => setSearchText(e.target.value)} />
          <Select value={importanceFilter} onChange={setImportanceFilter} style={{ width: 120 }}
            options={[
              { value: 'all', label: '全部优先级' },
              { value: 'high', label: '高' },
              { value: 'medium', label: '中' },
              { value: 'low', label: '低' },
            ]} />
        </Space>

        <Table columns={columns} dataSource={filteredMemories} rowKey="id"
          size="middle" pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{ emptyText: '暂无记忆条目' }} />

        <Modal title={editingMemory ? '编辑记忆' : '新建记忆'} open={editModalOpen}
          onCancel={() => { setEditModalOpen(false); setEditingMemory(null); }}
          onOk={() => { editForm.submit(); }}
          destroyOnHidden>
          <Form form={editForm} layout="vertical" onFinish={handleSave}>
            <Form.Item name="content" label="内容" rules={[{ required: true, message: '请输入内容' }]}>
              <Input.TextArea rows={4} placeholder="记忆内容..." />
            </Form.Item>
            <Form.Item name="importance" label="重要性（1-10）" initialValue={5}>
              <InputNumber min={1} max={10} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="tags" label="标签（逗号分隔）">
              <Input placeholder="tag1, tag2, tag3" />
            </Form.Item>
          </Form>
        </Modal>

        <Drawer title="记忆详情" open={viewDrawerOpen}
          onClose={() => setViewDrawerOpen(false)} size="default" destroyOnHidden>
          {viewingMemory && (
            <>
              <div style={{ marginBottom: 16 }}>
                <Tag color={LAYER_LABELS[viewingMemory.layer]?.color || '#1677ff'}>
                  {LAYER_LABELS[viewingMemory.layer]?.label || viewingMemory.layer}
                </Tag>
                <Tag color={viewingMemory.importance >= 7 ? 'red' : viewingMemory.importance >= 4 ? 'orange' : 'default'}>
                  重要性: {viewingMemory.importance}
                </Tag>
              </div>
              <Paragraph strong>内容：</Paragraph>
              <Paragraph style={{ background: '#f5f5f5', padding: 12, borderRadius: 8 }}>
                {viewingMemory.content}
              </Paragraph>
              <div style={{ marginBottom: 8 }}>
                <Text type="secondary">来源：</Text> <Text>{viewingMemory.source || '-'}</Text>
              </div>
              <div style={{ marginBottom: 8 }}>
                <Text type="secondary">标签：</Text>
                <Space wrap>{viewingMemory.tags.map(t => <Tag key={t}>{t}</Tag>)}</Space>
              </div>
              <div style={{ marginBottom: 8 }}>
                <Text type="secondary">创建：</Text>
                <Text>{viewingMemory.created_at ? new Date(viewingMemory.created_at).toLocaleString() : '-'}</Text>
              </div>
              <div>
                <Text type="secondary">更新：</Text>
                <Text>{viewingMemory.updated_at ? new Date(viewingMemory.updated_at).toLocaleString() : '-'}</Text>
              </div>
            </>
          )}
        </Drawer>
      </Card>
    </div>
  );
};

export default MemoryPage;
