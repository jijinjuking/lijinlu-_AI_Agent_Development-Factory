/**
 * RuntimeOpsPage - 运行时运维页面
 * 覆盖: Scheduler / ModelRouter / Sandbox / LoopDetector / PolicyEngine
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  Tabs,
  Table,
  Button,
  Tag,
  Card,
  Space,
  Modal,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
  message,
  Popconfirm,
  Statistic,
  Row,
  Col,
  Tooltip,
  Badge,
  Typography,
  Divider,
  Alert,
} from 'antd';
import {
  ReloadOutlined,
  PlusOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  SettingOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  fetchWorkers,
  fetchSchedulerStatus,
  fetchSchedulerConfig,
  updateSchedulerConfig,
  pauseScheduler,
  resumeScheduler,
  type WorkerInfo,
  type SchedulerQueueStatus,
  type SchedulerConfig,
  fetchModels,
  fetchModelRouterConfig,
  updateModelRouterConfig,
  enableModel,
  disableModel,
  type ModelInfo,
  type ModelRouterConfig,
  fetchSandboxes,
  createSandbox,
  destroySandbox,
  destroyAllSandboxes,
  type SandboxInfo,
  fetchAllLoopStatuses,
  resetLoop,
  type LoopDetectorStatus,
  fetchPolicyRules,
  createPolicyRule,
  updatePolicyRule,
  deletePolicyRule,
  fetchAuditLogs,
  type PolicyRule,
  type AuditLogEntry,
} from '../api/runtime';

const { Text, Title } = Typography;

// ===== Scheduler Tab =====
function SchedulerTab() {
  const [status, setStatus] = useState<SchedulerQueueStatus | null>(null);
  const [config, setConfig] = useState<SchedulerConfig | null>(null);
  const [workers, setWorkers] = useState<WorkerInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [paused, setPaused] = useState(false);
  const [configModalOpen, setConfigModalOpen] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, c, w] = await Promise.all([
        fetchSchedulerStatus(),
        fetchSchedulerConfig(),
        fetchWorkers(),
      ]);
      setStatus(s);
      setConfig(c);
      setWorkers(w);
    } catch (e: unknown) {
      message.error(`加载失败: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleTogglePause = async () => {
    try {
      if (paused) {
        await resumeScheduler();
        message.success('调度器已恢复');
      } else {
        await pauseScheduler();
        message.success('调度器已暂停');
      }
      setPaused(!paused);
      load();
    } catch (e: unknown) {
      message.error(`操作失败: ${(e as Error).message}`);
    }
  };

  const handleSaveConfig = async () => {
    try {
      const values = await form.validateFields();
      await updateSchedulerConfig(values);
      message.success('配置已更新');
      setConfigModalOpen(false);
      load();
    } catch (e: unknown) {
      message.error(`保存失败: ${(e as Error).message}`);
    }
  };

  const workerColumns: ColumnsType<WorkerInfo> = [
    { title: 'Worker ID', dataIndex: 'worker_id', key: 'worker_id', width: 200, ellipsis: true },
    { title: '名称', dataIndex: 'name', key: 'name', width: 120 },
    {
      title: '能力', dataIndex: 'capabilities', key: 'capabilities', width: 160,
      render: (caps: string[]) => caps.map((c) => <Tag key={c}>{c}</Tag>),
    },
    {
      title: '负载', dataIndex: 'current_load', key: 'load', width: 100,
      render: (load: number, record: WorkerInfo) => `${load} / ${record.max_load}`,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (s: string) => <Badge status={s === 'active' ? 'success' : s === 'draining' ? 'warning' : 'default'} text={s} />,
    },
    { title: '心跳', dataIndex: 'last_heartbeat', key: 'last_heartbeat', width: 180 },
  ];

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card><Statistic title="队列长度" value={status?.queue_length ?? '-'} /></Card></Col>
        <Col span={6}><Card><Statistic title="运行中" value={status?.running ?? '-'} styles={{ content: { color: '#1890ff' }}} /></Card></Col>
        <Col span={6}><Card><Statistic title="Worker (活跃)" value={`${status?.workers_active ?? 0} / ${status?.workers_total ?? 0}`} /></Card></Col>
        <Col span={6}>
          <Card>
            <Space>
              <Button icon={paused ? <PlayCircleOutlined /> : <PauseCircleOutlined />} onClick={handleTogglePause}>
                {paused ? '恢复' : '暂停'}
              </Button>
              <Button icon={<SettingOutlined />} onClick={() => { form.setFieldsValue(config); setConfigModalOpen(true); }}>
                配置
              </Button>
              <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
            </Space>
          </Card>
        </Col>
      </Row>

      <Card title="Workers" style={{ marginBottom: 16 }}>
        <Table rowKey="worker_id" columns={workerColumns} dataSource={workers} loading={loading} pagination={false} size="small" />
      </Card>

      <Modal title="调度器配置" open={configModalOpen} onOk={handleSaveConfig} onCancel={() => setConfigModalOpen(false)} destroyOnHidden>
        <Form form={form} layout="vertical">
          <Form.Item name="max_retries" label="最大重试次数"><InputNumber min={0} max={10} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="default_timeout" label="默认超时 (秒)"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="enable_preemption" label="允许抢占" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name="queue_concurrency" label="队列并发数"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ===== Model Router Tab =====
function ModelRouterTab() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [config, setConfig] = useState<ModelRouterConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [configModalOpen, setConfigModalOpen] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [m, c] = await Promise.all([fetchModels(), fetchModelRouterConfig()]);
      setModels(m);
      setConfig(c);
    } catch (e: unknown) {
      message.error(`加载失败: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const modelColumns: ColumnsType<ModelInfo> = [
    { title: '模型', dataIndex: 'name', key: 'name', width: 160 },
    { title: 'Provider', dataIndex: 'provider', key: 'provider', width: 100 },
    { title: '上下文窗口', dataIndex: 'context_window', key: 'context_window', width: 120 },
    {
      title: '价格 (in/out)', key: 'price', width: 180,
      render: (_: unknown, r: ModelInfo) => `¥${r.input_price}/${r.output_price}`,
    },
    {
      title: '标签', dataIndex: 'tags', key: 'tags', width: 160,
      render: (tags: string[]) => tags?.map((t) => <Tag key={t}>{t}</Tag>),
    },
    {
      title: '状态', dataIndex: 'enabled', key: 'enabled', width: 80,
      render: (en: boolean) => <Badge status={en ? 'success' : 'default'} text={en ? '启用' : '禁用'} />,
    },
    {
      title: '操作', key: 'actions', width: 140,
      render: (_: unknown, r: ModelInfo) => (
        <Space>
          {r.enabled ? (
            <Button size="small" onClick={() => disableModel(r.model_id).then(load).catch(() => {})}>禁用</Button>
          ) : (
            <Button size="small" type="primary" onClick={() => enableModel(r.model_id).then(load).catch(() => {})}>启用</Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}><Card><Statistic title="默认模型" value={config?.default_model ?? '-'} styles={{ content: { fontSize: 14 } }} /></Card></Col>
        <Col span={8}><Card><Statistic title="模型总数" value={models.length} /></Card></Col>
        <Col span={8}>
          <Card>
            <Space>
              <Button icon={<SettingOutlined />} onClick={() => { form.setFieldsValue(config); setConfigModalOpen(true); }}>配置</Button>
              <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
            </Space>
          </Card>
        </Col>
      </Row>

      <Card title="模型列表">
        <Table rowKey="model_id" columns={modelColumns} dataSource={models} loading={loading} pagination={{ pageSize: 20 }} size="small" />
      </Card>

      <Modal title="路由配置" open={configModalOpen} onOk={async () => { try { const v = await form.validateFields(); await updateModelRouterConfig(v); message.success('配置已更新'); setConfigModalOpen(false); load(); } catch (e: unknown) { message.error(`保存失败: ${(e as Error).message}`); } }} onCancel={() => setConfigModalOpen(false)} destroyOnHidden>
        <Form form={form} layout="vertical">
          <Form.Item name="default_model" label="默认模型"><Input /></Form.Item>
          <Form.Item name="fallback_models" label="Fallback 模型"><Select mode="tags" placeholder="输入模型 ID" /></Form.Item>
          <Form.Item name="cost_aware" label="成本感知" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name="latency_aware" label="延迟感知" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ===== Sandbox Tab =====
function SandboxTab() {
  const [sandboxes, setSandboxes] = useState<SandboxInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try { setSandboxes(await fetchSandboxes()); } catch (e: unknown) { message.error(`加载失败: ${(e as Error).message}`); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      await createSandbox(values);
      message.success('沙箱已创建');
      setCreateModalOpen(false);
      load();
    } catch (e: unknown) { message.error(`创建失败: ${(e as Error).message}`); }
  };

  const handleDestroyAll = async () => {
    try { await destroyAllSandboxes(); message.success('已销毁所有沙箱'); load(); } catch (e: unknown) { message.error(`操作失败: ${(e as Error).message}`); }
  };

  const columns: ColumnsType<SandboxInfo> = [
    { title: 'Sandbox ID', dataIndex: 'sandbox_id', key: 'sandbox_id', width: 220, ellipsis: true },
    { title: '类型', dataIndex: 'sandbox_type', key: 'sandbox_type', width: 100 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (s: string) => <Badge status={s === 'ready' ? 'success' : s === 'running' ? 'processing' : s === 'error' ? 'error' : 'default'} text={s} />,
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
    {
      title: '操作', key: 'actions', width: 100,
      render: (_: unknown, r: SandboxInfo) => (
        <Popconfirm title="确认销毁此沙箱？" onConfirm={async () => { await destroySandbox(r.sandbox_id); load(); }}>
          <Button size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <Card
        title="沙箱管理"
        extra={
          <Space>
            <Button icon={<PlusOutlined />} type="primary" onClick={() => { form.resetFields(); setCreateModalOpen(true); }}>创建沙箱</Button>
            <Popconfirm title="确认销毁所有沙箱？" onConfirm={handleDestroyAll}><Button danger>全部销毁</Button></Popconfirm>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
          </Space>
        }
      >
        <Table rowKey="sandbox_id" columns={columns} dataSource={sandboxes} loading={loading} pagination={false} size="small" />
      </Card>

      <Modal title="创建沙箱" open={createModalOpen} onOk={handleCreate} onCancel={() => setCreateModalOpen(false)} destroyOnHidden>
        <Form form={form} layout="vertical">
          <Form.Item name="sandbox_type" label="沙箱类型" rules={[{ required: true }]}>
            <Select>
              <Select.Option value="python">Python Sandbox</Select.Option>
              <Select.Option value="docker">Docker Sandbox</Select.Option>
              <Select.Option value="browser">Browser Sandbox</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ===== Loop Detector Tab =====
function LoopDetectorTab() {
  const [statuses, setStatuses] = useState<LoopDetectorStatus[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { setStatuses(await fetchAllLoopStatuses()); } catch (e: unknown) { message.error(`加载失败: ${(e as Error).message}`); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const columns: ColumnsType<LoopDetectorStatus> = [
    { title: 'Task ID', dataIndex: 'task_id', key: 'task_id', width: 260, ellipsis: true },
    {
      title: '循环中', dataIndex: 'is_looping', key: 'is_looping', width: 100,
      render: (v: boolean) => v ? <Tag color="red">是</Tag> : <Tag color="green">否</Tag>,
    },
    { title: '当前迭代', dataIndex: 'iteration_count', key: 'iteration_count', width: 100 },
    { title: '最大迭代', dataIndex: 'max_iterations', key: 'max_iterations', width: 100 },
    { title: '循环类型', dataIndex: 'loop_type', key: 'loop_type', width: 120 },
    { title: '自动恢复', dataIndex: 'auto_recovery', key: 'auto_recovery', width: 100, render: (v: boolean) => v ? '是' : '否' },
    {
      title: '操作', key: 'actions', width: 100,
      render: (_: unknown, r: LoopDetectorStatus) => (
        <Popconfirm title="确认重置此任务的循环检测？" onConfirm={async () => { await resetLoop(r.task_id); load(); }}>
          <Button size="small">重置</Button>
        </Popconfirm>
      ),
    },
  ];

  const loopingCount = statuses.filter((s) => s.is_looping).length;

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}><Card><Statistic title="检测到循环的任务" value={loopingCount} styles={{ content: { color: loopingCount > 0 ? '#ff4d4f' : '#52c41a' } }} /></Card></Col>
        <Col span={8}><Card><Statistic title="监控中任务总数" value={statuses.length} /></Card></Col>
        <Col span={8}><Card><Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button></Card></Col>
      </Row>
      {loopingCount > 0 && <Alert type="warning" message={`${loopingCount} 个任务检测到无限循环，请及时处理`} showIcon style={{ marginBottom: 16 }} />}
      <Card title="循环检测状态">
        <Table rowKey="task_id" columns={columns} dataSource={statuses} loading={loading} pagination={{ pageSize: 20 }} size="small" />
      </Card>
    </div>
  );
}

// ===== Policy Engine Tab =====
function PolicyEngineTab() {
  const [rules, setRules] = useState<PolicyRule[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [ruleModalOpen, setRuleModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<PolicyRule | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, logs] = await Promise.all([fetchPolicyRules(), fetchAuditLogs({ limit: 100 })]);
      setRules(r);
      setAuditLogs(logs);
    } catch (e: unknown) {
      message.error(`加载失败: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSaveRule = async () => {
    try {
      const values = await form.validateFields();
      if (editingRule) {
        await updatePolicyRule(editingRule.rule_id, values);
        message.success('规则已更新');
      } else {
        await createPolicyRule(values);
        message.success('规则已创建');
      }
      setRuleModalOpen(false);
      load();
    } catch (e: unknown) {
      message.error(`保存失败: ${(e as Error).message}`);
    }
  };

  const ruleColumns: ColumnsType<PolicyRule> = [
    { title: '规则名称', dataIndex: 'name', key: 'name', width: 160 },
    { title: '资源', dataIndex: 'resource', key: 'resource', width: 160 },
    { title: '动作', dataIndex: 'action', key: 'action', width: 120 },
    {
      title: '效果', dataIndex: 'effect', key: 'effect', width: 100,
      render: (e: string) => <Tag color={e === 'allow' ? 'green' : e === 'deny' ? 'red' : 'orange'}>{e}</Tag>,
    },
    { title: '优先级', dataIndex: 'priority', key: 'priority', width: 80 },
    {
      title: '状态', dataIndex: 'enabled', key: 'enabled', width: 80,
      render: (v: boolean) => <Badge status={v ? 'success' : 'default'} text={v ? '启用' : '禁用'} />,
    },
    {
      title: '操作', key: 'actions', width: 140,
      render: (_: unknown, r: PolicyRule) => (
        <Space>
          <Button size="small" onClick={() => { setEditingRule(r); form.setFieldsValue(r); setRuleModalOpen(true); }}>编辑</Button>
          <Popconfirm title="确认删除此规则？" onConfirm={async () => { await deletePolicyRule(r.rule_id); load(); }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const auditColumns: ColumnsType<AuditLogEntry> = [
    { title: '时间', dataIndex: 'timestamp', key: 'timestamp', width: 180 },
    { title: 'Task ID', dataIndex: 'task_id', key: 'task_id', width: 220, ellipsis: true },
    { title: '动作', dataIndex: 'action', key: 'action', width: 120 },
    { title: '资源', dataIndex: 'resource', key: 'resource', width: 160 },
    {
      title: '决策', dataIndex: 'decision', key: 'decision', width: 80,
      render: (d: string) => <Tag color={d === 'allow' ? 'green' : 'red'}>{d}</Tag>,
    },
    { title: '原因', dataIndex: 'reason', key: 'reason', ellipsis: true },
  ];

  return (
    <div>
      <Card
        title="策略规则"
        extra={
          <Space>
            <Button icon={<PlusOutlined />} type="primary" onClick={() => { setEditingRule(null); form.resetFields(); setRuleModalOpen(true); }}>新建规则</Button>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Table rowKey="rule_id" columns={ruleColumns} dataSource={rules} loading={loading} pagination={false} size="small" />
      </Card>

      <Card title="审计日志">
        <Table rowKey="log_id" columns={auditColumns} dataSource={auditLogs} loading={loading} pagination={{ pageSize: 20 }} size="small" />
      </Card>

      <Modal title={editingRule ? '编辑规则' : '新建规则'} open={ruleModalOpen} onOk={handleSaveRule} onCancel={() => setRuleModalOpen(false)} destroyOnHidden width={600}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="规则名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="resource" label="资源" rules={[{ required: true }]}><Input placeholder="如 tasks, models, sandbox" /></Form.Item>
          <Form.Item name="action" label="动作" rules={[{ required: true }]}><Input placeholder="如 create, delete, execute" /></Form.Item>
          <Form.Item name="effect" label="效果" rules={[{ required: true }]}>
            <Select>
              <Select.Option value="allow">Allow</Select.Option>
              <Select.Option value="deny">Deny</Select.Option>
              <Select.Option value="conditional">Conditional</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="priority" label="优先级"><InputNumber min={0} max={100} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch defaultChecked /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ===== Main Page =====
const tabItems = [
  { key: 'scheduler', label: '调度器 (Scheduler)', children: <SchedulerTab /> },
  { key: 'model-router', label: '模型路由 (Model Router)', children: <ModelRouterTab /> },
  { key: 'sandbox', label: '沙箱 (Sandbox)', children: <SandboxTab /> },
  { key: 'loop-detector', label: '循环检测 (Loop Detector)', children: <LoopDetectorTab /> },
  { key: 'policy', label: '策略引擎 (Policy Engine)', children: <PolicyEngineTab /> },
];

export default function RuntimeOpsPage() {
  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>运行时运维中心</Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        统一管理调度器、模型路由、沙箱、循环检测和策略引擎
      </Text>
      <Tabs type="card" items={tabItems} />
    </div>
  );
}
