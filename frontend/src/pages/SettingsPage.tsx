// ============================================================
// SettingsPage — 系统设置（真实 API）
// ============================================================

import React, { useState, useEffect } from 'react';
import {
  Typography, Card, Tabs, Table, Switch, Tag, Button, Space,
  Form, Input, Select, AutoComplete, InputNumber, Modal, App,
  Popconfirm, Spin, Radio, Badge,
} from 'antd';
import {
  SettingOutlined, ApiOutlined, RobotOutlined, SafetyOutlined,
  PlusOutlined, DeleteOutlined, EditOutlined,
  CheckCircleOutlined, CloseCircleOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  fetchModels, fetchApiKeys, fetchPermissions,
  createModel, updateModel, deleteModel,
  createApiKey, deleteApiKey,
  updatePermission,
  fetchRuntimeSettings, updateRuntimeSettings,
} from '../api/settings';
import type { ModelConfig, ApiKey, AgentPermission, RuntimeSettings } from '../types/settings';
import { fetchAgents, createAgent, updateAgent, deleteAgent } from '../api/agents';
import type { Agent, AgentRole } from '../types/agent';
import { AGENT_ROLE_LABELS, AGENT_ROLE_COLORS } from '../types/agent';

const { Title, Text } = Typography;

const providerLabels: Record<string, string> = {
  openai: 'OpenAI', anthropic: 'Anthropic', ollama: 'Ollama (本地)', custom: '自定义',
};

const providerColors: Record<string, string> = {
  openai: '#10a37f', anthropic: '#d4a574', ollama: '#000000', custom: '#8c8c8c',
};

const SettingsPage: React.FC = () => {
  const { message } = App.useApp();
  const [activeTab, setActiveTab] = useState('models');
  const [addKeyModalOpen, setAddKeyModalOpen] = useState(false);
  const [keyForm] = Form.useForm();

  // API
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [permissions, setPermissions] = useState<AgentPermission[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [modelModalOpen, setModelModalOpen] = useState(false);
  const [modelForm] = Form.useForm();
  const [editingModel, setEditingModel] = useState<ModelConfig | null>(null);

  // Permission edit
  const [permModalOpen, setPermModalOpen] = useState(false);
  const [permForm] = Form.useForm();
  const [editingPerm, setEditingPerm] = useState<AgentPermission | null>(null);

  // Add agent modal
  const [addAgentModalOpen, setAddAgentModalOpen] = useState(false);
  const [addAgentForm] = Form.useForm();

  // System prompt editor
  const [promptVisible, setPromptVisible] = useState(false);
  const [promptAgent, setPromptAgent] = useState<Agent | null>(null);
  const [promptText, setPromptText] = useState('');
  const [promptSaving, setPromptSaving] = useState(false);

  const renderPerm = (v: boolean) => v
    ? <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 16 }} />
    : <CloseCircleOutlined style={{ color: '#d9d9d9', fontSize: 16 }} />;

  useEffect(() => {
    setLoading(true);
    Promise.all([fetchModels(), fetchApiKeys(), fetchPermissions(), fetchAgents(), fetchRuntimeSettings()])
      .then(([m, k, p, a, rs]) => { setModels(m); setApiKeys(k); setPermissions(p); setAgents(a); setRuntimeSettings(rs); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // 更新单项运行时设置
  const updateRuntime = async (key: keyof RuntimeSettings, value: unknown) => {
    if (!runtimeSettings) return;
    const updated = { ...runtimeSettings, [key]: value };
    setRuntimeSettings(updated);
    try {
      await updateRuntimeSettings({ [key]: value });
    } catch {
      message.error('保存设置失败');
    }
  };

  const modelColumns: ColumnsType<ModelConfig> = [
    {
      title: '模型', dataIndex: 'name', key: 'name', width: 160,
      render: (name: string, r) => (
        <div>
          <Text strong>{name}</Text>
          <br />
          <Tag color={providerColors[r.provider] || '#8c8c8c'}>
            {providerLabels[r.provider] || r.provider}
          </Tag>
        </div>
      ),
    },
    {
      title: 'Model ID', dataIndex: 'model_id', key: 'model_id', width: 140,
      render: (v: string) => <Text code style={{ fontSize: 11 }}>{v || '-'}</Text>,
    },
    {
      title: 'API Key', dataIndex: 'api_key_label', key: 'api_key', width: 120,
      render: (v: string, r) => v
        ? <Tag color="green">{v}</Tag>
        : <Tag color="default">未配置</Tag>,
    },
    {
      title: '启用', dataIndex: 'enabled', key: 'enabled', width: 60,
      render: (v: boolean) => <Switch checked={v} size="small" disabled />,
    },
    {
      title: '操作', key: 'actions', width: 120, fixed: 'right' as const,
      render: (_, r) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EditOutlined />}
            onClick={() => { setEditingModel(r); modelForm.setFieldsValue(r); setModelModalOpen(true); }}>编辑</Button>
          <Popconfirm title="确定删除此模型？" okText="删除" cancelText="取消"
            onConfirm={async () => { await deleteModel(r.id); message.success('删除成功'); fetchModels().then(setModels); }}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const keyColumns: ColumnsType<ApiKey> = [
    { title: '提供商', dataIndex: 'provider', key: 'provider', width: 100,
      render: (v: string) => <Tag color={providerColors[v] || '#8c8c8c'}>
        {providerLabels[v] || v}</Tag> },
    { title: '标签', dataIndex: 'label', key: 'label' },
    { title: 'Key', dataIndex: 'masked_key', key: 'key', width: 180,
      render: (v: string) => <Text code>{v || '****'}</Text> },
    { title: '创建时间', dataIndex: 'created_at', key: 'created', width: 110,
      render: (v: string) => v ? new Date(v).toLocaleDateString() : '-' },
    { title: '操作', key: 'actions', width: 100, fixed: 'right' as const,
      render: (_, r) => (
        <Popconfirm title="确定删除此 Key？" okText="删除" cancelText="取消"
          onConfirm={async () => {
            try {
              await deleteApiKey(r.id);
              message.success('删除成功');
              fetchApiKeys().then(setApiKeys);
            } catch (e) {
              message.error('删除失败');
            }
          }}>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ) },
  ];

  const permColumns: ColumnsType<AgentPermission> = [
    { title: '角色', dataIndex: 'role_name', key: 'role_name', width: 100,
      render: (v: string) => <Text strong>{v}</Text> },
    { title: '角色ID', dataIndex: 'role_id', key: 'role_id', width: 100,
      render: (v: string) => <Tag>{v}</Tag> },
    {
      title: '创建Pipeline', dataIndex: 'can_create_pipeline', key: 'can_create_pipeline', width: 100,
      render: (v: boolean) => renderPerm(v),
    },
    {
      title: '部署', dataIndex: 'can_deploy', key: 'can_deploy', width: 70,
      render: (v: boolean) => renderPerm(v),
    },
    {
      title: '网络访问', dataIndex: 'can_access_network', key: 'can_access_network', width: 80,
      render: (v: boolean) => renderPerm(v),
    },
    {
      title: '写文件', dataIndex: 'can_write_files', key: 'can_write_files', width: 70,
      render: (v: boolean) => renderPerm(v),
    },
    {
      title: '执行命令', dataIndex: 'can_execute_commands', key: 'can_execute_commands', width: 80,
      render: (v: boolean) => renderPerm(v),
    },
    {
      title: '最大并发', dataIndex: 'max_concurrency', key: 'max_concurrency', width: 80,
      render: (v: number) => <Text>{v}</Text>,
    },
    {
      title: 'Token上限', dataIndex: 'max_tokens_per_task', key: 'max_tokens_per_task', width: 80,
      render: (v: number) => <Text>{v.toLocaleString()}</Text>,
    },
    {
      title: '日费用上限', dataIndex: 'max_daily_cost', key: 'max_daily_cost', width: 90,
      render: (v: number) => <Text>¥{v.toFixed(0)}</Text>,
    },
    {
      title: '操作', key: 'actions', width: 120, fixed: 'right' as const,
      render: (_, r) => (
        <Button type="link" size="small" icon={<EditOutlined />}
          onClick={() => { setEditingPerm(r); setPermModalOpen(true); }}>编辑</Button>
      ),
    },
  ];

  const agentColumns: ColumnsType<Agent> = [
    {
      title: 'Agent', dataIndex: 'name', key: 'name', width: 140,
      render: (name: string, r) => (
        <div>
          <Text strong>{name}</Text>
          <br />
          <Tag color={AGENT_ROLE_COLORS[r.role as AgentRole] || '#8c8c8c'}>
            {AGENT_ROLE_LABELS[r.role as AgentRole] || r.role}
          </Tag>
          {r.is_active !== false ? (
            <Tag color="success" style={{ fontSize: 11 }}>启用</Tag>
          ) : (
            <Tag color="default" style={{ fontSize: 11 }}>禁用</Tag>
          )}
        </div>
      ),
    },
    {
      title: '模型模式', dataIndex: 'model_mode', key: 'model_mode', width: 140,
      render: (mode: string, r) => (
        <Radio.Group
          value={mode || 'bound'}
          size="small"
          optionType="button"
          buttonStyle="solid"
          onChange={async (e) => {
            const newMode = e.target.value;
            try {
              await updateAgent(r.id, { model_mode: newMode } as Partial<Agent>);
              setAgents((prev) => prev.map((a) => (a.id === r.id ? { ...a, model_mode: newMode } : a)));
              message.success(`已切换为${newMode === 'bound' ? '绑定' : '自动'}模式`);
            } catch { message.error('更新失败'); }
          }}
        >
          <Radio.Button value="bound">绑定</Radio.Button>
          <Radio.Button value="auto">自动</Radio.Button>
        </Radio.Group>
      ),
    },
    {
      title: '指定模型', dataIndex: 'model', key: 'model', width: 200,
      render: (model: string, r) => {
        if (r.model_mode === 'auto') {
          return <Tag color="green">自动路由</Tag>;
        }
        return (
          <Select
            value={model}
            size="small"
            style={{ width: 160 }}
            options={models.map((m) => ({
              value: m.model_id || m.name,
              label: `${m.name} (${m.provider})`,
            }))}
            onChange={async (val) => {
              try {
                await updateAgent(r.id, { model: val } as Partial<Agent>);
                setAgents((prev) => prev.map((a) => (a.id === r.id ? { ...a, model: val } : a)));
                message.success(`模型已更新为 ${val}`);
              } catch { message.error('更新失败'); }
            }}
          />
        );
      },
    },
    {
      title: '提示词', key: 'prompt', width: 90,
      render: (_, r: Agent) => (
        <Button type="link" size="small"
          onClick={() => { setPromptAgent(r); setPromptVisible(true); }}>
          {r.system_prompt ? '已自定义' : '查看默认'}
        </Button>
      ),
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => {
        const map: Record<string, { color: string; text: string }> = {
          idle: { color: 'default', text: '空闲' },
          running: { color: 'processing', text: '运行中' },
          error: { color: 'error', text: '错误' },
          offline: { color: 'default', text: '离线' },
        };
        const info = map[s] || { color: 'default', text: s };
        return <Badge status={info.color as any} text={info.text} />;
      },
    },
    {
      title: '统计', key: 'stats', width: 160,
      render: (_, r: Agent) => (
        <div style={{ fontSize: 12, color: '#8c8c8c' }}>
          任务: {r.totalTasks || 0}/{r.completedTasks || 0}完成
          <br />
          Token: {(r.totalTokens || 0).toLocaleString()}
        </div>
      ),
    },
    {
      title: '操作', key: 'actions', width: 80, fixed: 'right' as const,
      render: (_, r: Agent) => (
        <Popconfirm title={`确定删除 Agent「${r.name}」？`} okText="删除" cancelText="取消"
          onConfirm={async () => {
            try {
              await deleteAgent(r.id);
              setAgents((prev) => prev.filter((a) => a.id !== r.id));
              message.success(`Agent「${r.name}」已删除`);
            } catch { message.error('删除失败'); }
          }}>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ];

  if (loading) {
    return (
      <div>
        <Title level={4}>系统设置</Title>
        <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
      </div>
    );
  }

  const tabItems = [
    {
      key: 'models',
      label: <Space><RobotOutlined />LLM 模型</Space>,
      children: (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
            <Text type="secondary">配置可用的 LLM 模型（{models.length} 个）</Text>
            <Button type="primary" size="small" icon={<PlusOutlined />}
              onClick={() => { setEditingModel(null); modelForm.resetFields(); setModelModalOpen(true); }}>添加模型</Button>
          </div>
          <Table columns={modelColumns} dataSource={models}
            rowKey="id" size="middle" pagination={false} />
        </>
      ),
    },
    {
      key: 'apikeys',
      label: <Space><ApiOutlined />API Keys</Space>,
      children: (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
            <Text type="secondary">管理第三方 API Key（{apiKeys.length} 个）</Text>
            <Button type="primary" size="small" icon={<PlusOutlined />}
              onClick={() => setAddKeyModalOpen(true)}>添加 Key</Button>
          </div>
          <Table columns={keyColumns} dataSource={apiKeys}
            rowKey="id" size="middle" pagination={false} />
        </>
      ),
    },
    {
      key: 'permissions',
      label: <Space><SafetyOutlined />Agent 权限</Space>,
      children: (
        <>
          <div style={{ marginBottom: 16 }}>
            <Text type="secondary">
              按角色控制 Agent 的能力边界：Pipeline 创建、部署、网络访问、文件写入、命令执行、并发/Token/费用上限。点击「编辑」修改。（{permissions.length} 个角色）
            </Text>
          </div>
          <Table columns={permColumns} dataSource={permissions}
            rowKey="id" size="middle" pagination={false} />
        </>
      ),
    },
    {
      key: 'agents',
      label: <Space><UserOutlined />Agent 配置</Space>,
      children: (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
            <Text type="secondary">
              管理 Agent 的模型绑定模式：<Tag color="blue">绑定</Tag> 强制使用指定模型，<Tag color="green">自动</Tag> 由系统智能路由（{agents.length} 个）
            </Text>
            <Button type="primary" size="small" icon={<PlusOutlined />}
              onClick={() => { addAgentForm.resetFields(); setAddAgentModalOpen(true); }}>添加 Agent</Button>
          </div>
          <Table columns={agentColumns} dataSource={agents}
            rowKey="id" size="middle" pagination={false} />
        </>
      ),
    },
    {
      key: 'general',
      label: <Space><SettingOutlined />通用设置</Space>,
      children: runtimeSettings ? (
        <div style={{ maxWidth: 600 }}>
          <Card size="small" title="系统参数" style={{ marginBottom: 16 }}>
            <Form layout="vertical">
              <Form.Item label="最大并发 Agent 数">
                <InputNumber min={1} max={20} value={runtimeSettings.max_concurrency} style={{ width: 120 }}
                  onChange={(v) => updateRuntime('max_concurrency', v ?? 8)} />
              </Form.Item>
              <Form.Item label="默认任务超时 (分钟)">
                <InputNumber min={1} max={120} value={runtimeSettings.default_timeout_minutes} style={{ width: 120 }}
                  onChange={(v) => updateRuntime('default_timeout_minutes', v ?? 30)} />
              </Form.Item>
              <Form.Item label="自动重试次数">
                <InputNumber min={0} max={5} value={runtimeSettings.auto_retry_count} style={{ width: 120 }}
                  onChange={(v) => updateRuntime('auto_retry_count', v ?? 2)} />
              </Form.Item>
              <Form.Item label="日志保留天数">
                <InputNumber min={1} max={365} value={runtimeSettings.log_retention_days} style={{ width: 120 }}
                  onChange={(v) => updateRuntime('log_retention_days', v ?? 30)} />
              </Form.Item>
            </Form>
          </Card>
          <Card size="small" title="通知设置">
            <Form layout="vertical">
              <Form.Item label="任务完成通知">
                <Switch checked={runtimeSettings.notify_on_complete}
                  onChange={(v) => updateRuntime('notify_on_complete', v)} />
              </Form.Item>
              <Form.Item label="任务失败通知">
                <Switch checked={runtimeSettings.notify_on_failure}
                  onChange={(v) => updateRuntime('notify_on_failure', v)} />
              </Form.Item>
              <Form.Item label="费用告警阈值 (¥/天)">
                <InputNumber min={1} max={1000} value={runtimeSettings.cost_alert_threshold} style={{ width: 120 }} prefix="¥"
                  onChange={(v) => updateRuntime('cost_alert_threshold', v ?? 20)} />
              </Form.Item>
              <Form.Item label="通知渠道">
                <Select mode="multiple" value={runtimeSettings.notification_channels} style={{ width: 300 }}
                  onChange={(v) => updateRuntime('notification_channels', v)}
                  options={[
                    { value: 'webhook', label: 'Webhook' },
                    { value: 'slack', label: 'Slack' },
                    { value: 'email', label: 'Email' },
                  ]} />
              </Form.Item>
            </Form>
          </Card>
        </div>
      ) : (
        <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>系统设置</Title>
        <Text type="secondary">LLM 模型配置、API Key 管理、Agent 权限和系统参数</Text>
      </div>

      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
      </Card>

      <Modal title="添加 Agent" open={addAgentModalOpen}
        onCancel={() => setAddAgentModalOpen(false)}
        onOk={() => { addAgentForm.submit(); }}
        destroyOnHidden forceRender
        afterOpenChange={(open) => { if (open) addAgentForm.resetFields(); }}>
        <Form form={addAgentForm} layout="vertical" onFinish={async (v) => {
          try {
            const newAgent = await createAgent({
              name: v.name,
              role: v.role,
              model: v.model || 'gpt-4o',
              model_mode: v.model_mode || 'bound',
              description: v.description || '',
              system_prompt: v.system_prompt || null,
              capability_tags: v.capability_tags || '',
            } as Partial<Agent>);
            setAgents((prev) => [...prev, newAgent as unknown as Agent]);
            message.success(`Agent「${v.name}」创建成功`);
            setAddAgentModalOpen(false);
            // 重新加载以获取完整的后端生成字段
            fetchAgents().then(setAgents);
          } catch (e: any) {
            message.error(e?.message || '创建失败');
          }
        }}>
          <Form.Item name="name" label="Agent 名称" rules={[{ required: true, message: '请输入 Agent 名称' }]}>
            <Input placeholder="例：Code Reviewer" maxLength={128} />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true, message: '请输入或选择角色' }]} initialValue="开发者">
            <AutoComplete
              options={[
                { value: '架构师', label: '架构师 (architect)' },
                { value: '开发者', label: '开发者 (developer)' },
                { value: '审查员', label: '审查员 (reviewer)' },
                { value: '测试员', label: '测试员 (tester)' },
                { value: '部署员', label: '部署员 (deployer)' },
              ]}
              placeholder="输入或选择角色名，如：架构师、桌面端开发"
              filterOption={(input, option) =>
                (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
                || (option?.value as string)?.includes(input)
              }
              style={{ width: '100%' }}
            />
          </Form.Item>
          <Form.Item name="model_mode" label="模型模式" initialValue="bound">
            <Radio.Group optionType="button" buttonStyle="solid">
              <Radio.Button value="bound">绑定指定模型</Radio.Button>
              <Radio.Button value="auto">自动智能路由</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item name="model" label="绑定模型" initialValue="gpt-4o">
            <Select
              placeholder="选择模型"
              options={models.map((m) => ({ value: m.model_id || m.name, label: `${m.name} (${m.provider})` }))}
            />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="Agent 的简短描述..." maxLength={256} />
          </Form.Item>
          <Form.Item name="system_prompt" label="自定义系统提示词">
            <Input.TextArea rows={4} placeholder="留空使用角色默认提示词" style={{ fontFamily: 'monospace' }} />
          </Form.Item>
          <Form.Item name="capability_tags" label="能力标签">
            <Input placeholder="例：code-review,security,performance（逗号分隔）" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="添加 API Key" open={addKeyModalOpen}
        onCancel={() => setAddKeyModalOpen(false)}
        onOk={() => { keyForm.submit(); }}
        destroyOnHidden forceRender>
        <Form form={keyForm} layout="vertical" onFinish={async (v) => {
          try {
            await createApiKey(v);
            message.success('API Key 添加成功');
            setAddKeyModalOpen(false);
            const [m, k, p] = await Promise.all([fetchModels(), fetchApiKeys(), fetchPermissions()]);
            setModels(m); setApiKeys(k); setPermissions(p);
          } catch (e) {
            message.error('添加失败');
          }
        }}>
          <Form.Item name="provider" label="提供商" rules={[{ required: true }]}>
            <Select options={[
              { value: 'openai', label: 'OpenAI' },
              { value: 'anthropic', label: 'Anthropic' },
              { value: 'custom', label: '自定义' },
            ]} />
          </Form.Item>
          <Form.Item name="label" label="标签" rules={[{ required: true }]}>
            <Input placeholder="例：生产环境 Key" />
          </Form.Item>
          <Form.Item name="key" label="API Key" rules={[{ required: true }]}>
            <Input.Password placeholder="sk-..." />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={editingModel ? '编辑模型' : '添加模型'} open={modelModalOpen}
        onCancel={() => { setModelModalOpen(false); setEditingModel(null); }}
        onOk={() => { modelForm.submit(); }}
        destroyOnHidden forceRender>
        <Form form={modelForm} layout="vertical" onFinish={async (v) => {
          try {
            if (editingModel) {
              await updateModel(editingModel.id, v);
              message.success('模型更新成功');
            } else {
              await createModel(v);
              message.success('模型添加成功');
            }
            setModelModalOpen(false);
            setEditingModel(null);
            fetchModels().then(setModels);
          } catch (e) {
            message.error('操作失败');
          }
        }}>
          <Form.Item name="name" label="模型名称" rules={[{ required: true }]}>
            <Input placeholder="例：GPT-4o" />
          </Form.Item>
          <Form.Item name="model_id" label="Model ID" rules={[{ required: true }]}>
            <Input placeholder="例：gpt-4o" />
          </Form.Item>
          <Form.Item name="provider" label="提供商" rules={[{ required: true }]}>
            <Select options={[
              { value: 'openai', label: 'OpenAI' },
              { value: 'anthropic', label: 'Anthropic' },
              { value: 'ollama', label: 'Ollama (本地)' },
              { value: 'custom', label: '自定义' },
            ]} />
          </Form.Item>
          <Form.Item name="api_base" label="API Base URL">
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>
          <Form.Item name="api_key_id" label="API Key">
            <Select
              placeholder="选择 API Key（可选）"
              allowClear
              options={apiKeys.map((k) => ({
                value: k.id,
                label: `${k.label} (${k.masked_key})`,
              }))}
              popupRender={(menu) => (
                <>
                  {menu}
                  <div style={{ borderTop: '1px solid #f0f0f0', padding: '8px' }}>
                    <Button type="link" size="small" icon={<PlusOutlined />}
                      onClick={() => { setModelModalOpen(false); setActiveTab('apikeys'); setAddKeyModalOpen(true); }}>
                      添加新 Key
                    </Button>
                  </div>
                </>
              )}
            />
          </Form.Item>
          <Form.Item name="cost_input_per_1k" label="输入成本 ($/1K tokens)">
            <InputNumber min={0} step={0.0001} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="cost_output_per_1k" label="输出成本 ($/1K tokens)">
            <InputNumber min={0} step={0.0001} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="max_tokens" label="最大 Token 数">
            <InputNumber min={1} max={131072} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch defaultChecked />
          </Form.Item>
          <Form.Item name="is_default" label="设为默认" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={`编辑权限: ${editingPerm?.role_name || ''}`} open={permModalOpen}
        onCancel={() => { setPermModalOpen(false); setEditingPerm(null); }}
        onOk={() => { permForm.submit(); }}
        afterOpenChange={(open) => {
          if (open && editingPerm) {
            permForm.setFieldsValue(editingPerm);
          }
        }}
        destroyOnHidden forceRender>
        <Form form={permForm} layout="vertical" onFinish={async (v) => {
          if (!editingPerm) return;
          try {
            await updatePermission(editingPerm.role_id, v);
            message.success('权限已更新');
            setPermModalOpen(false);
            setEditingPerm(null);
            fetchPermissions().then(setPermissions);
          } catch { message.error('更新失败'); }
        }}>
          <Form.Item name="can_create_pipeline" label="允许创建 Pipeline" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="can_deploy" label="允许部署" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="can_access_network" label="允许网络访问" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="can_write_files" label="允许写文件" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="can_execute_commands" label="允许执行命令" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="max_concurrency" label="最大并发数">
            <InputNumber min={1} max={20} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="max_tokens_per_task" label="单任务 Token 上限">
            <InputNumber min={1000} max={200000} step={1000} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="max_daily_cost" label="日费用上限 (¥)">
            <InputNumber min={0} max={1000} step={1} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={
          <Space>
            <span>Agent 提示词: {promptAgent?.name}</span>
            <Tag color={promptAgent ? AGENT_ROLE_COLORS[promptAgent.role as AgentRole] : '#8c8c8c'}>
              {promptAgent ? AGENT_ROLE_LABELS[promptAgent.role as AgentRole] : ''}
            </Tag>
            {promptAgent?.system_prompt ? (
              <Tag color="orange">自定义</Tag>
            ) : (
              <Tag color="green">角色默认</Tag>
            )}
          </Space>
        }
        open={promptVisible}
        width={800}
        onCancel={() => { setPromptVisible(false); setPromptAgent(null); }}
        footer={[
          <Button key="reset" disabled={!promptAgent?.system_prompt}
            onClick={async () => {
              if (!promptAgent) return;
              setPromptSaving(true);
              try {
                await updateAgent(promptAgent.id, { system_prompt: null } as Partial<Agent>);
                setAgents((prev) => prev.map((a) => (a.id === promptAgent.id ? { ...a, system_prompt: null } : a)));
                setPromptAgent({ ...promptAgent, system_prompt: null });
                setPromptText('');
                message.success('已恢复为角色默认提示词');
              } catch { message.error('重置失败'); }
              finally { setPromptSaving(false); }
            }}>
            恢复默认
          </Button>,
          <Button key="cancel" onClick={() => { setPromptVisible(false); setPromptAgent(null); }}>
            取消
          </Button>,
          <Button key="save" type="primary" loading={promptSaving}
            onClick={async () => {
              if (!promptAgent) return;
              setPromptSaving(true);
              try {
                await updateAgent(promptAgent.id, { system_prompt: promptText || null } as Partial<Agent>);
                setAgents((prev) => prev.map((a) => (a.id === promptAgent.id ? { ...a, system_prompt: promptText || null } : a)));
                message.success('提示词已保存');
                setPromptVisible(false);
                setPromptAgent(null);
              } catch { message.error('保存失败'); }
              finally { setPromptSaving(false); }
            }}>
            保存
          </Button>,
        ]}
        afterOpenChange={(open) => {
          if (open && promptAgent) {
            setPromptText(promptAgent.system_prompt || '');
          }
        }}
        destroyOnHidden
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          自定义提示词会覆盖角色默认提示词。留空保存则恢复默认。下方为角色默认内容供参考。
        </Text>
        <Input.TextArea
          value={promptText || undefined}
          onChange={(e) => setPromptText(e.target.value)}
          placeholder={
            !promptAgent?.system_prompt
              ? '留空使用角色默认提示词。在下方参考区域查看默认内容。'
              : '输入自定义系统提示词...'
          }
          rows={16}
          style={{ fontFamily: 'monospace', fontSize: 13 }}
        />
        <div style={{
          marginTop: 16, padding: 12,
          background: '#f6f8fa', borderRadius: 6, maxHeight: 300, overflow: 'auto',
        }}>
          <Text type="secondary" strong>角色默认提示词参考：</Text>
          <pre style={{
            margin: '8px 0 0', fontSize: 12, whiteSpace: 'pre-wrap', color: '#57606a',
          }}>
            {/* 角色默认提示词通过后端 API 获取，这里显示占位 */}
            {(() => {
              const hints: Record<string, string> = {
                architect: '系统架构师 — 需求分析 → 架构设计 → 方案对比 → 接口定义 → 风险点识别',
                developer: '全栈开发 — 理解需求 → 小步迭代 → 防御性编程 → 测试驱动 → 可读性优先',
                tester: '测试工程师 — 分层测试 → 边界优先 → 等价类划分 → 可复现 → 覆盖率意识',
                reviewer: '代码审查 — 分层审查 → 风险分级 → 建设性反馈 → 安全敏感 → 性能意识',
                deployer: 'DevOps — 基础设施即代码 → 渐进式发布 → 可观测性 → 安全基线 → 容灾意识',
              };
              const role = promptAgent?.role || 'developer';
              return `当前角色: ${AGENT_ROLE_LABELS[role as AgentRole] || role}\n方法论: ${hints[role] || hints.developer}\n\n详细提示词请查看后端 app/prompts/roles.py`;
            })()}
          </pre>
        </div>
      </Modal>
    </div>
  );
};

export default SettingsPage;
