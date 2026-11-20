/**
 * FederationPage - 运行时联邦管理页面
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Table, Button, Tag, Card, Space, message, Popconfirm, Badge, Typography, Tooltip, Statistic, Row, Col, Descriptions } from 'antd';
import { ReloadOutlined, PlusOutlined, DeleteOutlined, SyncOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { fetchMembers, removeMember, triggerSync, fetchSyncStatuses, type FederationMember, type FederationSyncStatus } from '../api/federation';

const { Text, Paragraph } = Typography;

const statusColors: Record<string, 'success' | 'default' | 'processing' | 'error'> = {
  online: 'success', offline: 'default', syncing: 'processing',
};

export default function FederationPage() {
  const [members, setMembers] = useState<FederationMember[]>([]);
  const [syncStatuses, setSyncStatuses] = useState<FederationSyncStatus[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [m, s] = await Promise.all([fetchMembers(), fetchSyncStatuses()]);
      setMembers(m);
      setSyncStatuses(s);
    } catch (e: unknown) { message.error(`加载失败: ${(e as Error).message}`); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleRemove = async (memberId: string) => {
    try { await removeMember(memberId); message.success('成员已移除'); load(); } catch (e: unknown) { message.error(`移除失败: ${(e as Error).message}`); }
  };

  const handleSync = async (memberId?: string) => {
    try { await triggerSync(memberId); message.success('同步已触发'); load(); } catch (e: unknown) { message.error(`同步失败: ${(e as Error).message}`); }
  };

  const getSync = (memberId: string) => syncStatuses.find((s) => s.member_id === memberId);

  const memberColumns: ColumnsType<FederationMember> = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 140, ellipsis: true },
    { title: '地址', dataIndex: 'address', key: 'address', width: 220, ellipsis: true },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (s: string) => <Badge status={statusColors[s] ?? 'default'} text={s} /> },
    { title: '版本', dataIndex: 'runtime_version', key: 'runtime_version', width: 100 },
    { title: '能力', dataIndex: 'capabilities', key: 'capabilities', width: 160, render: (caps: string[]) => caps?.map((c) => <Tag key={c}>{c}</Tag>) },
    { title: '最后在线', dataIndex: 'last_seen', key: 'last_seen', width: 180 },
    {
      title: '同步状态', key: 'sync', width: 100,
      render: (_: unknown, r: FederationMember) => {
        const sync = getSync(r.member_id);
        if (!sync) return '-';
        return <Tag color={sync.sync_status === 'idle' ? 'green' : sync.sync_status === 'syncing' ? 'blue' : 'red'}>{sync.sync_status}</Tag>;
      },
    },
    {
      title: '操作', key: 'actions', width: 160,
      render: (_: unknown, r: FederationMember) => (
        <Space>
          <Tooltip title="同步"><Button size="small" icon={<SyncOutlined />} onClick={() => handleSync(r.member_id)} /></Tooltip>
          <Popconfirm title="确认移除？" onConfirm={() => handleRemove(r.member_id)}><Tooltip title="移除"><Button size="small" danger icon={<DeleteOutlined />} /></Tooltip></Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}><Card><Statistic title="联邦成员" value={members.length} /></Card></Col>
        <Col span={8}><Card><Statistic title="在线" value={members.filter((m) => m.status === 'online').length} styles={{ content: { color: '#52c41a' } }} /></Card></Col>
        <Col span={8}><Card><Space><Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button><Button type="primary" icon={<PlusOutlined />} disabled>加入联邦</Button><Button icon={<SyncOutlined />} onClick={() => handleSync()}>全局同步</Button></Space></Card></Col>
      </Row>

      <Card title="联邦成员管理" style={{ marginBottom: 16 }}>
        <Table rowKey="member_id" columns={memberColumns} dataSource={members} loading={loading} pagination={false} size="small" scroll={{ x: 1200 }} />
      </Card>

      {syncStatuses.length > 0 && (
        <Card title="同步状态详情">
          <Descriptions column={2} bordered size="small">
            {syncStatuses.map((s) => (
              <Descriptions.Item key={s.member_id} label={s.member_id} labelStyle={{ width: 220 }}>
                {s.sync_status} | 待处理: {s.pending_items} | 最后同步: {s.last_sync}
                {s.error_message && <Text type="danger"> {s.error_message}</Text>}
              </Descriptions.Item>
            ))}
          </Descriptions>
        </Card>
      )}

      <Paragraph type="secondary" style={{ marginTop: 8 }}>Runtime Federation — 多运行时实例状态同步、能力共享、联邦调度</Paragraph>
    </div>
  );
}
