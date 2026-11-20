// ============================================================
// PipelinesPage — 流程编排（真实 API）
// ============================================================

import React, { useState, useMemo, useEffect } from 'react';
import {
  Typography, Card, Row, Col, Button, Tag, Table, Space,
  Input, Select, Modal, Form, Steps, Progress, Statistic, Empty, Spin, App,
} from 'antd';
import {
  PlusOutlined, PlayCircleOutlined, PauseCircleOutlined,
  EyeOutlined, ThunderboltOutlined, ClockCircleOutlined,
  CheckCircleOutlined, CloseCircleOutlined, SyncOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { fetchTemplates, fetchRuns, createTemplate, updateTemplate, startPipeline, pauseRun, resumeRun } from '../api/pipelines';
import { fetchAgents } from '../api/agents';
import type { PipelineTemplate, PipelineRun } from '../types/pipeline';
import type { Agent } from '../types/agent';
import {
  STEP_TYPE_LABELS, STEP_TYPE_COLORS, PIPELINE_CATEGORIES,
} from '../constants/pipeline';

const { Title, Text, Paragraph } = Typography;
const { Search } = Input;

const statusIcon = (status: string) => {
  switch (status) {
    case 'running': return <SyncOutlined spin style={{ color: '#1677ff' }} />;
    case 'completed': return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
    case 'failed': return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
    case 'paused': return <PauseCircleOutlined style={{ color: '#faad14' }} />;
    default: return null;
  }
};

const statusLabel: Record<string, string> = {
  running: '运行中', completed: '已完成', failed: '已失败', paused: '已暂停', waiting: '等待中',
};

const PipelinesPage: React.FC = () => {
  const { message } = App.useApp();
  const [view, setView] = useState<'templates' | 'runs'>('templates');
  const [searchText, setSearchText] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [selectedTpl, setSelectedTpl] = useState<PipelineTemplate | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingTplId, setEditingTplId] = useState<string | null>(null);
  const [form] = Form.useForm();
  const [editForm] = Form.useForm();

  // API 数据
  const [templates, setTemplates] = useState<PipelineTemplate[]>([]);
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [agents, setAgents] = useState<Agent[]>([]);

  // 步骤编辑器
  const [steps, setSteps] = useState<Array<{
    id: string;
    name: string;
    type: string;
    agent_role: string;
    description: string;
  }>>([]);

  useEffect(() => {
    setLoading(true);
    Promise.all([fetchTemplates(), fetchRuns(), fetchAgents()])
      .then(([tpls, rns, ags]) => { setTemplates(tpls); setRuns(rns); setAgents(ags); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const addStep = () => {
    const idx = steps.length + 1;
    setSteps([...steps, {
      id: `step-${Date.now()}-${idx}`,
      name: '',
      type: 'agent',
      agent_role: '',
      description: '',
    }]);
  };

  const removeStep = (index: number) => {
    setSteps(steps.filter((_, i) => i !== index));
  };

  const updateStep = (index: number, field: string, value: string) => {
    const next = [...steps];
    next[index] = { ...next[index], [field]: value };
    setSteps(next);
  };

  const resetCreateForm = () => {
    form.resetFields();
    setSteps([]);
  };

  const openEditModal = (tpl: PipelineTemplate) => {
    setEditingTplId(tpl.id);
    editForm.setFieldsValue({
      name: tpl.name,
      category: tpl.category || 'custom',
      tags: Array.isArray(tpl.tags) ? tpl.tags.join(', ') : (tpl.tags || ''),
      description: tpl.description || '',
    });
    setSteps((tpl.steps || []).map((s: any, i: number) => ({
      id: s.id || `step-${Date.now()}-${i}`,
      name: s.name || '',
      type: s.type || 'agent',
      agent_role: s.agent_role || '',
      description: s.description || '',
    })));
    setDetailModalOpen(false);
    setEditModalOpen(true);
  };

  const resetEditForm = () => {
    editForm.resetFields();
    setSteps([]);
    setEditingTplId(null);
  };

  const filteredTemplates = useMemo(() => {
    return templates.filter((t) => {
      const matchSearch = !searchText || t.name.includes(searchText) || t.description.includes(searchText);
      const matchCat = categoryFilter === 'all' || t.category === categoryFilter;
      return matchSearch && matchCat;
    });
  }, [templates, searchText, categoryFilter]);

  const runColumns: ColumnsType<PipelineRun> = [
    { title: 'Pipeline', key: 'name', width: 200,
      render: (_, r) => <Text strong>{r.template_name || r.template_id}</Text> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (s: string) => (
        <Space>{statusIcon(s)}<Text>{statusLabel[s] || s}</Text></Space>
      ) },
    { title: '进度', key: 'progress', width: 160,
      render: (_, r) => (
        <Progress percent={r.progress ?? 0}
          size="small" style={{ width: 120 }}
          status={r.status === 'failed' ? 'exception' : r.status === 'completed' ? 'success' : 'active'} />
      ) },
    { title: '当前步骤', key: 'step', width: 120,
      render: (_, r) => r.current_step_name || r.current_step_id || '-' },
    { title: '创建时间', dataIndex: 'created_at', key: 'time', width: 120,
      render: (v: string) => v ? new Date(v).toLocaleTimeString('zh-CN') : '-' },
    { title: '操作', key: 'actions', width: 160,
      render: (_, r) => (
        <Space size="small">
          {r.status === 'running' && (
            <Button type="link" size="small" icon={<PauseCircleOutlined />}
              onClick={async () => { await pauseRun(r.id); fetchRuns().then(setRuns); }}>暂停</Button>
          )}
          {r.status === 'paused' && (
            <Button type="link" size="small" icon={<PlayCircleOutlined />}
              onClick={async () => { await resumeRun(r.id); fetchRuns().then(setRuns); }}>恢复</Button>
          )}
          <Button type="link" size="small" icon={<EyeOutlined />}>详情</Button>
        </Space>
      ) },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>流程编排</Title>
          <Text type="secondary">可视化设计和组合 Agent 工作流，一键触发执行</Text>
        </div>
        <Space>
          <Button icon={<PlayCircleOutlined />} onClick={() => setView('runs')}
            type={view === 'runs' ? 'primary' : 'default'}>运行记录</Button>
          <Button icon={<ThunderboltOutlined />} onClick={() => setView('templates')}
            type={view === 'templates' ? 'primary' : 'default'}>流程模板</Button>
          <Button type="primary" icon={<PlusOutlined />}
            onClick={() => { resetCreateForm(); setCreateModalOpen(true); }}>新建流程</Button>
        </Space>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
      ) : view === 'templates' ? (
        <>
          <Card size="small" style={{ marginBottom: 16 }}>
            <Space wrap>
              <Search placeholder="搜索流程模板..." allowClear style={{ width: 280 }}
                onSearch={setSearchText} onChange={(e) => setSearchText(e.target.value)} />
              <Select value={categoryFilter} onChange={setCategoryFilter} style={{ width: 140 }}
                options={[{ value: 'all', label: '全部分类' },
                  ...Object.entries(PIPELINE_CATEGORIES).map(([k, v]) => ({ value: k, label: v })),
                ]} />
            </Space>
          </Card>

          <Row gutter={[16, 16]}>
            {filteredTemplates.map((tpl) => (
              <Col xs={24} sm={12} lg={8} key={tpl.id}>
                <Card hoverable size="small"
                  onClick={() => { setSelectedTpl(tpl); setDetailModalOpen(true); }}
                  style={{ height: '100%' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <Text strong style={{ fontSize: 15 }}>{tpl.name}</Text>
                    <Tag color="#1677ff">{PIPELINE_CATEGORIES[tpl.category] || tpl.category}</Tag>
                  </div>
                  <Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ marginBottom: 12, minHeight: 42 }}>
                    {tpl.description}
                  </Paragraph>
                  <Space wrap size={[4, 4]} style={{ marginBottom: 12 }}>
                    {tpl.tags.map((tag) => <Tag key={tag} color="blue">{tag}</Tag>)}
                  </Space>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <Space size={16}>
                      <span>
                        <ClockCircleOutlined style={{ marginRight: 4, color: '#8c8c8c' }} />
                        <Text type="secondary">{tpl.steps.length} 步</Text>
                      </span>
                    </Space>
                    <Text type="secondary">v1.0</Text>
                  </div>
                </Card>
              </Col>
            ))}
          </Row>

          {filteredTemplates.length === 0 && (
            <Empty description="没有匹配的流程模板" />
          )}
        </>
      ) : (
        <Card>
          <Table columns={runColumns} dataSource={runs}
            rowKey="id" size="middle" pagination={{ pageSize: 10 }}
            locale={{ emptyText: '暂无运行记录' }} />
        </Card>
      )}

      {/* 创建流程 Modal */}
      <Modal title="新建流程" open={createModalOpen}
        onCancel={() => { setCreateModalOpen(false); resetCreateForm(); }}
        onOk={() => { form.submit(); }}
        width={720} destroyOnHidden forceRender>
        <Form form={form} layout="vertical" onFinish={async (v) => {
          try {
            const payload = {
              name: v.name,
              description: v.description || '',
              category: v.category || 'custom',
              tags: v.tags ? v.tags.split(',').map((s: string) => s.trim()).filter(Boolean) : [],
              steps: steps.map((s, i) => ({
                id: s.id,
                name: s.name,
                type: s.type,
                agent_role: s.agent_role,
                description: s.description,
                next_steps: i < steps.length - 1 ? [steps[i + 1].id] : [],
              })),
            };
            await createTemplate(payload as any);
            message.success('流程模板创建成功');
            setCreateModalOpen(false);
            resetCreateForm();
            const [tpls, rns] = await Promise.all([fetchTemplates(), fetchRuns()]);
            setTemplates(tpls);
            setRuns(rns);
          } catch (e) {
            message.error('创建失败');
          }
        }}>
          <Form.Item name="name" label="流程名称" rules={[{ required: true }]}>
            <Input placeholder="例：用户认证模块开发" />
          </Form.Item>
          <Form.Item name="category" label="分类" initialValue="custom">
            <Select options={Object.entries(PIPELINE_CATEGORIES).map(([k, v]) => ({ value: k, label: v }))} />
          </Form.Item>
          <Form.Item name="tags" label="标签（逗号分隔）">
            <Input placeholder="例：交易, 支付, 自动化" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="描述此流程的用途和执行逻辑" />
          </Form.Item>

          {/* 步骤编辑器 */}
          <div style={{ marginTop: 16, marginBottom: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <Text strong>流程步骤</Text>
              <Button type="dashed" size="small" icon={<PlusOutlined />} onClick={addStep}>添加步骤</Button>
            </div>
            {steps.length === 0 && (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无步骤，点击上方添加" style={{ margin: '16px 0' }} />
            )}
            {steps.map((step, i) => (
              <Card key={step.id} size="small" style={{ marginBottom: 12 }} styles={{ body: { padding: 12 } }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <Text strong style={{ fontSize: 13 }}>步骤 {i + 1}</Text>
                  <Button type="text" size="small" danger icon={<CloseCircleOutlined />}
                    onClick={() => removeStep(i)}>删除</Button>
                </div>
                <Row gutter={[12, 8]}>
                  <Col span={12}>
                    <Input size="small" placeholder="步骤名称" value={step.name}
                      onChange={(e) => updateStep(i, 'name', e.target.value)} />
                  </Col>
                  <Col span={6}>
                    <Select size="small" value={step.type}
                      onChange={(v) => updateStep(i, 'type', v)}
                      options={Object.entries(STEP_TYPE_LABELS).map(([k, v]) => ({ value: k, label: v }))}
                      style={{ width: '100%' }} />
                  </Col>
                  <Col span={6}>
                    {step.type === 'agent' ? (
                      <Select size="small" value={step.agent_role || undefined}
                        placeholder="选择 Agent"
                        onChange={(v) => updateStep(i, 'agent_role', v)}
                        options={agents.map((a) => ({ value: a.id, label: a.name || a.role || a.id }))}
                        style={{ width: '100%' }} allowClear />
                    ) : (
                      <Input size="small" disabled placeholder="非 Agent 步骤" />
                    )}
                  </Col>
                  <Col span={24}>
                    <Input.TextArea size="small" rows={2} placeholder="步骤描述"
                      value={step.description}
                      onChange={(e) => updateStep(i, 'description', e.target.value)} />
                  </Col>
                </Row>
              </Card>
            ))}
          </div>
        </Form>
      </Modal>

      {/* 模板详情 Modal */}
      <Modal title={selectedTpl?.name} open={detailModalOpen}
        onCancel={() => setDetailModalOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setDetailModalOpen(false)}>关闭</Button>,
          <Button key="edit" onClick={() => selectedTpl && openEditModal(selectedTpl)}>编辑</Button>,
          <Button key="run" type="primary" icon={<PlayCircleOutlined />}
            onClick={async () => {
              if (!selectedTpl) return;
              try {
                await startPipeline(selectedTpl.id);
                message.success('流程已启动');
                setDetailModalOpen(false);
                fetchRuns().then(setRuns);
              } catch (e) {
                message.error('启动失败');
              }
            }}>立即执行</Button>,
        ]}
        width={720} destroyOnHidden forceRender>
        {selectedTpl && (
          <>
            <Paragraph type="secondary" style={{ marginBottom: 16 }}>
              {selectedTpl.description}
            </Paragraph>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={8}>
                <Statistic title="步骤数" value={selectedTpl.steps.length} suffix="步" />
              </Col>
              <Col span={8}>
                <Statistic title="分类" value={PIPELINE_CATEGORIES[selectedTpl.category] || selectedTpl.category} />
              </Col>
              <Col span={8}>
                <Statistic title="创建时间" value={selectedTpl.created_at ? new Date(selectedTpl.created_at).toLocaleDateString() : '-'} />
              </Col>
            </Row>
            <Text strong style={{ display: 'block', marginBottom: 8 }}>流程步骤：</Text>
            <Steps orientation="vertical" size="small" current={-1}
              items={selectedTpl.steps.map((s) => ({
                title: <Space>
                  <Tag color={STEP_TYPE_COLORS[s.type as keyof typeof STEP_TYPE_COLORS] || '#1677ff'}>
                    {STEP_TYPE_LABELS[s.type as keyof typeof STEP_TYPE_LABELS] || s.type}
                  </Tag>
                  {s.name}
                </Space>,
                description: s.config ? JSON.stringify(s.config) : '',
              }))} />
          </>
        )}
      </Modal>

      {/* 编辑流程 Modal */}
      <Modal title="编辑流程" open={editModalOpen}
        onCancel={() => { setEditModalOpen(false); resetEditForm(); }}
        onOk={() => { editForm.submit(); }}
        width={720} destroyOnHidden forceRender>
        <Form form={editForm} layout="vertical" onFinish={async (v) => {
          try {
            const payload = {
              name: v.name,
              description: v.description || '',
              category: v.category || 'custom',
              tags: v.tags ? v.tags.split(',').map((s: string) => s.trim()).filter(Boolean) : [],
              steps: steps.map((s, i) => ({
                id: s.id,
                name: s.name,
                type: s.type,
                agent_role: s.agent_role,
                description: s.description,
                next_steps: i < steps.length - 1 ? [steps[i + 1].id] : [],
              })),
            };
            await updateTemplate(editingTplId!, payload as any);
            message.success('流程模板已更新');
            setEditModalOpen(false);
            resetEditForm();
            const [tpls, rns] = await Promise.all([fetchTemplates(), fetchRuns()]);
            setTemplates(tpls);
            setRuns(rns);
          } catch (e) {
            message.error('更新失败');
          }
        }}>
          <Form.Item name="name" label="流程名称" rules={[{ required: true }]}>
            <Input placeholder="例：用户认证模块开发" />
          </Form.Item>
          <Form.Item name="category" label="分类" initialValue="custom">
            <Select options={Object.entries(PIPELINE_CATEGORIES).map(([k, v]) => ({ value: k, label: v }))} />
          </Form.Item>
          <Form.Item name="tags" label="标签（逗号分隔）">
            <Input placeholder="例：交易, 支付, 自动化" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="描述此流程的用途和执行逻辑" />
          </Form.Item>

          <div style={{ marginTop: 16, marginBottom: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <Text strong>流程步骤</Text>
              <Button type="dashed" size="small" icon={<PlusOutlined />} onClick={addStep}>添加步骤</Button>
            </div>
            {steps.length === 0 && (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无步骤，点击上方添加" style={{ margin: '16px 0' }} />
            )}
            {steps.map((step, i) => (
              <Card key={step.id} size="small" style={{ marginBottom: 12 }} styles={{ body: { padding: 12 } }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <Text strong style={{ fontSize: 13 }}>步骤 {i + 1}</Text>
                  <Button type="text" size="small" danger icon={<CloseCircleOutlined />}
                    onClick={() => removeStep(i)}>删除</Button>
                </div>
                <Row gutter={[12, 8]}>
                  <Col span={12}>
                    <Input size="small" placeholder="步骤名称" value={step.name}
                      onChange={(e) => updateStep(i, 'name', e.target.value)} />
                  </Col>
                  <Col span={6}>
                    <Select size="small" value={step.type}
                      onChange={(v) => updateStep(i, 'type', v)}
                      options={Object.entries(STEP_TYPE_LABELS).map(([k, v]) => ({ value: k, label: v }))}
                      style={{ width: '100%' }} />
                  </Col>
                  <Col span={6}>
                    {step.type === 'agent' ? (
                      <Select size="small" value={step.agent_role || undefined}
                        placeholder="选择 Agent"
                        onChange={(v) => updateStep(i, 'agent_role', v)}
                        options={agents.map((a) => ({ value: a.id, label: a.name || a.role || a.id }))}
                        style={{ width: '100%' }} allowClear />
                    ) : (
                      <Input size="small" disabled placeholder="非 Agent 步骤" />
                    )}
                  </Col>
                  <Col span={24}>
                    <Input.TextArea size="small" rows={2} placeholder="步骤描述"
                      value={step.description}
                      onChange={(e) => updateStep(i, 'description', e.target.value)} />
                  </Col>
                </Row>
              </Card>
            ))}
          </div>
        </Form>
      </Modal>
    </div>
  );
};

export default PipelinesPage;
