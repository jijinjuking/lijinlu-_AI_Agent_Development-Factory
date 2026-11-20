/**
 * EvaluationPage - 评估系统页面
 * 覆盖: Evaluation Runner / Dataset / Metrics / Comparison
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Tabs, Table, Button, Tag, Card, Space, Modal, Form, Input, Select,
  message, Popconfirm, Row, Col, Statistic, Tooltip, Badge, Typography,
  Progress, Dropdown, Menu, Radio,
} from 'antd';
import {
  PlusOutlined, ReloadOutlined, DeleteOutlined, PlayCircleOutlined,
  BarChartOutlined, SwapOutlined, UploadOutlined, DownloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  fetchEvaluationRuns, fetchEvaluationRun, createEvaluationRun,
  updateEvaluationRun, deleteEvaluationRun, cancelEvaluationRun, rerunEvaluation,
  fetchDatasets, fetchDataset, createDataset, updateDataset, deleteDataset,
  fetchEvaluationCases, createEvaluationCase, updateEvaluationCase, deleteEvaluationCase, batchCreateCases,
  fetchMetrics, computeMetrics, compareRuns,
  type EvaluationRun, type EvaluationCase, type Dataset, type EvaluationMetric, type EvaluationResult,
} from '../api/evaluation';
import { fetchModels } from '../api/runtime';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

type EvaluationStatus = EvaluationRun['status'];

const statusColors: Record<EvaluationStatus, 'default' | 'processing' | 'success' | 'error' | 'warning'> = {
  pending: 'default',
  running: 'processing',
  completed: 'success',
  failed: 'error',
  canceled: 'warning',
};

// ===== Runs Tab =====
function RunsTab() {
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRun, setEditingRun] = useState<EvaluationRun | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [models, setModels] = useState<{ model_id: string; name: string }[]>([]);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, d, m] = await Promise.all([
        fetchEvaluationRuns(),
        fetchDatasets(),
        fetchModels(),
      ]);
      setRuns(r);
      setDatasets(d);
      setModels(m.map((x) => ({ model_id: x.model_id, name: x.name })));
    } catch (e: unknown) {
      message.error(`加载失败: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = () => {
    setEditingRun(null);
    form.resetFields();
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      if (editingRun) {
        await updateEvaluationRun(editingRun.run_id, values);
        message.success('评估任务已更新');
      } else {
        await createEvaluationRun(values);
        message.success('评估任务已创建');
      }
      setModalOpen(false);
      load();
    } catch (e: unknown) {
      message.error(`操作失败: ${(e as Error).message}`);
    }
  };

  const handleDelete = async (runId: string) => {
    try { await deleteEvaluationRun(runId); message.success('已删除'); load(); } catch (e: unknown) { message.error(`删除失败: ${(e as Error).message}`); }
  };

  const handleExecute = async (runId: string) => {
    try { await updateEvaluationRun(runId, { status: 'running' }); message.success('已提交执行'); load(); } catch (e: unknown) { message.error(`执行失败: ${(e as Error).message}`); }
  };

  const columns: ColumnsType<EvaluationRun> = [
    {
      title: '名称', dataIndex: 'name', key: 'name', width: 180, ellipsis: true,
      render: (name: string, r: EvaluationRun) => (
        <a onClick={async () => { const detail = await fetchEvaluationRun(r.run_id); Modal.info({ title: `评估详情 - ${detail.name}`, content: (<pre style={{ maxHeight: 400, overflow: 'auto' }}>{JSON.stringify(detail, null, 2)}</pre>) }); }}>{name}</a>
      ),
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (s: EvaluationStatus) => <Badge status={statusColors[s]} text={s} />,
    },
    {
      title: '指标', key: 'metrics', width: 200,
      render: (_: unknown, r: EvaluationRun) => r.metrics ? (
        <Space size="small" wrap>
          {Object.entries(r.metrics).map(([k, v]) => <Tag key={k}>{k}: {Number(v).toFixed(3)}</Tag>)}
        </Space>
      ) : '-',
    },
    { title: '模型', dataIndex: 'model_id', key: 'model_id', width: 140, ellipsis: true },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
    {
      title: '操作', key: 'actions', width: 180,
      render: (_: unknown, r: EvaluationRun) => (
        <Space>
          {r.status === 'pending' && <Tooltip title="执行"><Button size="small" type="link" icon={<PlayCircleOutlined />} onClick={() => handleExecute(r.run_id)} /></Tooltip>}
          {r.status === 'running' && <Tooltip title="取消"><Button size="small" type="link" danger icon={<DeleteOutlined />} onClick={async () => { await cancelEvaluationRun(r.run_id); load(); }} /></Tooltip>}
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(r.run_id)}><Tooltip title="删除"><Button size="small" type="link" danger icon={<DeleteOutlined />} /></Tooltip></Popconfirm>
          {r.status === 'completed' && <Tooltip title="重新运行"><Button size="small" type="link" icon={<PlayCircleOutlined />} onClick={async () => { await rerunEvaluation(r.run_id); message.success('已重新提交'); load(); }} /></Tooltip>}
        </Space>
      ),
    },
  ];

  const stats = {
    total: runs.length,
    running: runs.filter((r) => r.status === 'running').length,
    completed: runs.filter((r) => r.status === 'completed').length,
    failed: runs.filter((r) => r.status === 'failed').length,
  };

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card><Statistic title="总任务" value={stats.total} /></Card></Col>
        <Col span={6}><Card><Statistic title="执行中" value={stats.running} styles={{ content: { color: '#1890ff' } }} /></Card></Col>
        <Col span={6}><Card><Statistic title="已完成" value={stats.completed} styles={{ content: { color: '#52c41a' } }} /></Card></Col>
        <Col span={6}><Card><Statistic title="失败" value={stats.failed} styles={{ content: { color: '#ff4d4f' } }} /></Card></Col>
      </Row>

      <Card
        title="评估任务"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新建评估</Button>
          </Space>
        }
      >
        <Table rowKey="run_id" columns={columns} dataSource={runs} loading={loading} pagination={{ pageSize: 20 }} size="small" />
      </Card>

      <Modal title={editingRun ? '编辑评估任务' : '新建评估任务'} open={modalOpen} onOk={handleSubmit} onCancel={() => setModalOpen(false)} destroyOnHidden width={600}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="任务名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="dataset_id" label="数据集" rules={[{ required: true }]}>
            <Select placeholder="选择数据集">
              {datasets.map((d) => <Select.Option key={d.dataset_id} value={d.dataset_id}>{d.name} ({d.case_count} 条)</Select.Option>)}
            </Select>
          </Form.Item>
          <Form.Item name="model_id" label="评估模型" rules={[{ required: true }]}>
            <Select placeholder="选择模型">
              {models.map((m) => <Select.Option key={m.model_id} value={m.model_id}>{m.name}</Select.Option>)}
            </Select>
          </Form.Item>
          <Form.Item name="config" label="配置 (JSON)"><TextArea rows={3} placeholder='{"temperature": 0.0}' /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ===== Datasets Tab =====
function DatasetsTab() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingDs, setEditingDs] = useState<Dataset | null>(null);
  const [casesModalOpen, setCasesModalOpen] = useState(false);
  const [currentDataset, setCurrentDataset] = useState<Dataset | null>(null);
  const [cases, setCases] = useState<EvaluationCase[]>([]);
  const [casesLoading, setCasesLoading] = useState(false);
  const [form] = Form.useForm();
  const [casesForm] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try { setDatasets(await fetchDatasets()); } catch (e: unknown) { message.error(`加载失败: ${(e as Error).message}`); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const loadCases = useCallback(async (datasetId: string) => {
    setCasesLoading(true);
    try { setCases(await fetchEvaluationCases(datasetId)); } catch (e: unknown) { message.error(`加载用例失败: ${(e as Error).message}`); } finally { setCasesLoading(false); }
  }, []);

  const handleCreate = () => {
    setEditingDs(null);
    form.resetFields();
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      if (editingDs) {
        await updateDataset(editingDs.dataset_id, values);
        message.success('数据集已更新');
      } else {
        await createDataset(values);
        message.success('数据集已创建');
      }
      setModalOpen(false);
      load();
    } catch (e: unknown) { message.error(`操作失败: ${(e as Error).message}`); }
  };

  const handleDelete = async (dsId: string) => {
    try { await deleteDataset(dsId); message.success('已删除'); load(); } catch (e: unknown) { message.error(`删除失败: ${(e as Error).message}`); }
  };

  const handleViewCases = (ds: Dataset) => {
    setCurrentDataset(ds);
    setCasesModalOpen(true);
    loadCases(ds.dataset_id);
  };

  const handleAddCase = async () => {
    if (!currentDataset) return;
    try {
      const values = await casesForm.validateFields();
      await createEvaluationCase(currentDataset.dataset_id, values);
      message.success('用例已添加');
      casesForm.resetFields();
      loadCases(currentDataset.dataset_id);
    } catch (e: unknown) { message.error(`添加失败: ${(e as Error).message}`); }
  };

  const handleDeleteCase = async (caseId: string) => {
    if (!currentDataset) return;
    try { await deleteEvaluationCase(caseId); message.success('用例已删除'); loadCases(currentDataset.dataset_id); } catch (e: unknown) { message.error(`删除失败: ${(e as Error).message}`); }
  };

  const dsColumns: ColumnsType<Dataset> = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 180, render: (n: string, r: Dataset) => <a onClick={() => handleViewCases(r)}>{n}</a> },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    { title: '用例数', dataIndex: 'case_count', key: 'case_count', width: 80, align: 'center' as const },
    { title: '标签', dataIndex: 'tags', key: 'tags', width: 160, render: (tags?: string[]) => tags?.map((t) => <Tag key={t}>{t}</Tag>) },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 180 },
    {
      title: '操作', key: 'actions', width: 140,
      render: (_: unknown, r: Dataset) => (
        <Space>
          <Button size="small" onClick={() => { setEditingDs(r); form.setFieldsValue(r); setModalOpen(true); }}>编辑</Button>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(r.dataset_id)}><Button size="small" danger>删除</Button></Popconfirm>
        </Space>
      ),
    },
  ];

  const caseColumns: ColumnsType<EvaluationCase> = [
    { title: '输入', dataIndex: 'input', key: 'input', ellipsis: true },
    { title: '期望输出', dataIndex: 'expected_output', key: 'expected_output', ellipsis: true },
    {
      title: '上下文', dataIndex: 'context', key: 'context', width: 160,
      render: (ctx?: string[]) => ctx?.map((c, i) => <Tag key={i}>{c.slice(0, 20)}</Tag>),
    },
    {
      title: '操作', key: 'actions', width: 80,
      render: (_: unknown, r: EvaluationCase) => (
        <Popconfirm title="确认删除？" onConfirm={() => handleDeleteCase(r.case_id)}><Button size="small" danger>删除</Button></Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <Card
        title="数据集管理"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新建数据集</Button>
          </Space>
        }
      >
        <Table rowKey="dataset_id" columns={dsColumns} dataSource={datasets} loading={loading} pagination={{ pageSize: 20 }} size="small" />
      </Card>

      {/* 数据集编辑弹窗 */}
      <Modal title={editingDs ? '编辑数据集' : '新建数据集'} open={modalOpen} onOk={handleSubmit} onCancel={() => setModalOpen(false)} destroyOnHidden>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="数据集名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><TextArea rows={2} /></Form.Item>
          <Form.Item name="tags" label="标签"><Select mode="tags" placeholder="输入标签" /></Form.Item>
        </Form>
      </Modal>

      {/* 用例管理弹窗 */}
      <Modal title={`用例管理 - ${currentDataset?.name || ''}`} open={casesModalOpen} onCancel={() => setCasesModalOpen(false)} footer={null} width={800} destroyOnHidden>
        <div style={{ marginBottom: 16 }}>
          <Form form={casesForm} layout="inline">
            <Form.Item name="input" rules={[{ required: true, message: '请输入' }]} style={{ width: '40%' }}>
              <Input placeholder="输入 (input)" />
            </Form.Item>
            <Form.Item name="expected_output" style={{ width: '40%' }}>
              <Input placeholder="期望输出 (可选)" />
            </Form.Item>
            <Form.Item>
              <Button type="primary" icon={<PlusOutlined />} onClick={handleAddCase}>添加用例</Button>
            </Form.Item>
          </Form>
        </div>
        <Table rowKey="case_id" columns={caseColumns} dataSource={cases} loading={casesLoading} pagination={{ pageSize: 20 }} size="small" scroll={{ x: 600 }} />
      </Modal>
    </div>
  );
}

// ===== Metrics Tab =====
function MetricsTab() {
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [metrics, setMetrics] = useState<EvaluationMetric[]>([]);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [computed, setComputed] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, m] = await Promise.all([fetchEvaluationRuns({ status: 'completed' }), fetchMetrics()]);
      setRuns(r);
      setMetrics(m);
    } catch (e: unknown) { message.error(`加载失败: ${(e as Error).message}`); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCompute = async () => {
    if (!selectedRun) { message.warning('请先选择评估任务'); return; }
    try {
      const metricIds = metrics.map((m) => m.metric_id);
      const result = await computeMetrics(selectedRun, metricIds);
      setComputed(result);
      message.success('指标计算完成');
    } catch (e: unknown) { message.error(`计算失败: ${(e as Error).message}`); }
  };

  const runOptions = runs.map((r) => ({ label: `${r.name} (${r.run_id.slice(0, 8)}...)`, value: r.run_id }));

  return (
    <div>
      <Card title="指标计算" style={{ marginBottom: 16 }}>
        <Space size="large">
          <Space>
            <Text>选择评估任务:</Text>
            <Select placeholder="选择已完成的评估任务" style={{ width: 320 }} value={selectedRun} onChange={setSelectedRun} options={runOptions} />
          </Space>
          <Button type="primary" icon={<BarChartOutlined />} onClick={handleCompute} disabled={!selectedRun}>计算指标</Button>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
        </Space>
      </Card>

      {Object.keys(computed).length > 0 && (
        <Card title="计算结果">
          <Row gutter={16}>
            {Object.entries(computed).map(([k, v]) => (
              <Col span={6} key={k}><Card><Statistic title={k} value={Number(v).toFixed(4)} /></Card></Col>
            ))}
          </Row>
        </Card>
      )}

      <Card title="可用指标" style={{ marginTop: 16 }}>
        <Table
          rowKey="metric_id"
          columns={[
            { title: '指标名称', dataIndex: 'name', key: 'name' },
            { title: '描述', dataIndex: 'description', key: 'description' },
            { title: '类型', dataIndex: 'metric_type', key: 'metric_type' },
          ]}
          dataSource={metrics}
          loading={loading}
          pagination={false}
          size="small"
        />
      </Card>
    </div>
  );
}

// ===== Comparison Tab =====
function ComparisonTab() {
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [selectedRuns, setSelectedRuns] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    try { setRuns(await fetchEvaluationRuns({ status: 'completed' })); } catch (e: unknown) { message.error(`加载失败: ${(e as Error).message}`); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCompare = async () => {
    if (selectedRuns.length < 2) { message.warning('请至少选择 2 个评估任务'); return; }
    setLoading(true);
    try {
      const result = await compareRuns(selectedRuns);
      setComparison(result.comparison);
      message.success('对比完成');
    } catch (e: unknown) { message.error(`对比失败: ${(e as Error).message}`); } finally { setLoading(false); }
  };

  const runOptions = runs.map((r) => ({ label: `${r.name} (${r.model_id})`, value: r.run_id }));

  return (
    <div>
      <Card title="任务对比" style={{ marginBottom: 16 }}>
        <Space size="large">
          <Space>
            <Text>选择要对比的评估任务 (至少 2 个):</Text>
            <Select mode="multiple" placeholder="选择评估任务" style={{ width: 400 }} value={selectedRuns} onChange={setSelectedRuns} options={runOptions} maxTagCount={3} />
          </Space>
          <Button type="primary" icon={<SwapOutlined />} onClick={handleCompare} disabled={selectedRuns.length < 2} loading={loading}>开始对比</Button>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        </Space>
      </Card>

      {comparison && (
        <Card title="对比结果">
          <pre style={{ maxHeight: 500, overflow: 'auto', background: '#f5f5f5', padding: 16, borderRadius: 8 }}>
            {JSON.stringify(comparison, null, 2)}
          </pre>
        </Card>
      )}

      {!comparison && (
        <Card>
          <Paragraph type="secondary">请选择至少 2 个已完成的评估任务进行对比。对比结果将显示各任务的指标差异。</Paragraph>
        </Card>
      )}
    </div>
  );
}

// ===== Main Page =====
const tabItems = [
  { key: 'runs', label: '评估任务', children: <RunsTab /> },
  { key: 'datasets', label: '数据集', children: <DatasetsTab /> },
  { key: 'metrics', label: '指标计算', children: <MetricsTab /> },
  { key: 'comparison', label: '任务对比', children: <ComparisonTab /> },
];

export default function EvaluationPage() {
  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>评估系统</Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        管理评估任务、数据集、指标计算和任务对比
      </Text>
      <Tabs type="card" items={tabItems} />
    </div>
  );
}
