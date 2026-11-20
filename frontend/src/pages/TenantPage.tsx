/**
 * TenantPage - 多租户管理页面
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Table, Button, Tag, Card, Space, message, Popconfirm, Badge, Typography, Tooltip, Statistic, Row, Col, Progress, Modal, Form, Input, Select } from 'antd';
import { ReloadOutlined, PlusOutlined, DeleteOutlined, PauseCircleOutlined, CheckCircleOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { fetchTenants, suspendTenant, activateTenant, createTenant, deleteTenant, type Tenant, type TenantStatus } from '../api/tenant';

const { Text, Paragraph } = Typography;

const statusColors: Record<TenantStatus, 'success' | 'warning' | 'default'> = {
  active: 'success', suspended: 'warning', pending: 'default',
};

const planColors: Record<string, string> = { free: 'default', pro: 'blue', enterprise: 'purple' };

export default function TenantPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try { setTenants(await fetchTenants()); } catch (e: unknown) { message.error(`加载失败: ${(e as Error).message}`); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      await createTenant(values);
      message.success('租户已创建');
      setCreateModalOpen(false);
      load();
    } catch (e: unknown) { message.error(`创建失败: ${(e as Error).message}`); }
  };

  const handleSuspend = async (tenant: Tenant) => {
    try {
      if (tenant.status === 'active') { await suspendTenant(tenant.tenant_id); message.success('租户已停用'); } else { await activateTenant(tenant.tenant_id); message.success('租户已激活'); }
      load();
    } catch (e: unknown) { message.error(`操作失败: ${(e as Error).message}`); }
  };

  const handleDelete = async (tenantId: string) => {
    try { await deleteTenant(tenantId); message.success('租户已删除'); load(); } catch (e: unknown) { message.error(`删除失败: ${(e as Error).message}`); }
  };

  const columns: ColumnsType<Tenant> = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 140, ellipsis: true },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (s: TenantStatus) => <Badge status={statusColors[s]} text={s} /> },
    { title: '套餐', dataIndex: 'plan', key: 'plan', width: 100, render: (p: string) => <Tag color={planColors[p] ?? 'default'}>{p}</Tag> },
    { title: 'Owner', dataIndex: 'owner_email', key: 'owner_email', width: 200, ellipsis: true },
    {
      title: '资源用量', key: 'usage', width: 240,
      render: (_: unknown, r: Tenant) => (
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <Tooltip title={`${r.resource_usage.agents}/${r.resource_quota.max_agents}`}><Text style={{ fontSize: 11 }}>Agents: {r.resource_usage.agents}/{r.resource_quota.max_agents}</Text></Tooltip>
          <Tooltip title={`${r.resource_usage.concurrent_executions}/${r.resource_quota.max_concurrent_executions}`}><Text style={{ fontSize: 11 }}>并发: {r.resource_usage.concurrent_executions}/{r.resource_quota.max_concurrent_executions}</Text></Tooltip>
        </Space>
      ),
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
    {
      title: '操作', key: 'actions', width: 180,
      render: (_: unknown, r: Tenant) => (
        <Space>
          <Tooltip title={r.status === 'active' ? '停用' : '激活'}><Button size="small" onClick={() => handleSuspend(r)}>{r.status === 'active' ? <PauseCircleOutlined /> : <CheckCircleOutlined />}</Button></Tooltip>
          <Popconfirm title="确认删除租户？" onConfirm={() => handleDelete(r.tenant_id)}><Tooltip title="删除"><Button size="small" danger icon={<DeleteOutlined />} /></Tooltip></Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}><Card><Statistic title="租户总数" value={tenants.length} /></Card></Col>
        <Col span={8}><Card><Statistic title="活跃" value={tenants.filter((t) => t.status === 'active').length} styles={{ content: { color: '#52c41a' } }} /></Card></Col>
        <Col span={8}><Card><Space><Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setCreateModalOpen(true); }}>新建租户</Button></Space></Card></Col>
      </Row>

      <Card title="多租户管理">
        <Table rowKey="tenant_id" columns={columns} dataSource={tenants} loading={loading} pagination={{ pageSize: 20 }} size="small" scroll={{ x: 1200 }} />
        <Paragraph type="secondary" style={{ marginTop: 8 }}>Multi-Tenant System — 租户隔离、资源配额、用量追踪</Paragraph>
      </Card>

      <Modal title="新建租户" open={createModalOpen} onOk={handleCreate} onCancel={() => setCreateModalOpen(false)} destroyOnHidden>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="租户名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="owner_email" label="Owner 邮箱" rules={[{ required: true }, { type: 'email' }]}><Input /></Form.Item>
          <Form.Item name="plan" label="套餐" initialValue="free"><Select><Select.Option value="free">Free</Select.Option><Select.Option value="pro">Pro</Select.Option><Select.Option value="enterprise">Enterprise</Select.Option></Select></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
