/**
 * MultiNodePage - 多节点调度管理页面
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Table, Button, Tag, Card, Space, message, Popconfirm, Badge, Typography, Tooltip, Progress, Statistic, Row, Col, Modal, Form, Input, InputNumber, Drawer, Descriptions } from 'antd';
import { ReloadOutlined, PlusOutlined, DeleteOutlined, PauseCircleOutlined, PlayCircleOutlined, EyeOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { fetchNodes, deregisterNode, setNodeDraining, registerNode, type NodeInfo } from '../api/multiNode';

const { Text, Title } = Typography;
const { TextArea } = Input;

const statusColors: Record<string, 'success' | 'default' | 'warning'> = {
  online: 'success', offline: 'default', draining: 'warning',
};

export default function MultiNodePage() {
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState<NodeInfo | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try { setNodes(await fetchNodes()); } catch (e: unknown) { message.error(`加载失败: ${(e as Error).message}`); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleDrain = async (node: NodeInfo) => {
    try { await setNodeDraining(node.node_id, node.status !== 'draining'); message.success(node.status === 'draining' ? '已恢复' : '已设为排空'); load(); } catch (e: unknown) { message.error(`操作失败: ${(e as Error).message}`); }
  };

  const handleDelete = async (nodeId: string) => {
    try { await deregisterNode(nodeId); message.success('节点已移除'); load(); } catch (e: unknown) { message.error(`移除失败: ${(e as Error).message}`); }
  };

  const handleAddNode = async (values: any) => {
    setSubmitLoading(true);
    try {
      const data: any = {
        node_name: values.node_name,
        host: values.address.split(':')[0] || values.address,
        port: parseInt(values.address.split(':')[1]) || 8080,
      };
      
      if (values.capacity) {
        try {
          data.capacity = JSON.parse(values.capacity);
        } catch (e) {
          message.error('容量格式错误，请输入有效的 JSON');
          setSubmitLoading(false);
          return;
        }
      }
      
      if (values.labels) {
        try {
          data.labels = JSON.parse(values.labels);
        } catch (e) {
          message.error('标签格式错误，请输入有效的 JSON');
          setSubmitLoading(false);
          return;
        }
      }
      
      await registerNode(data);
      message.success('节点注册成功');
      setModalOpen(false);
      form.resetFields();
      load();
    } catch (e: unknown) {
      message.error(`注册失败: ${(e as Error).message}`);
    } finally {
      setSubmitLoading(false);
    }
  };

  const handleViewNode = (node: NodeInfo) => {
    setSelectedNode(node);
    setDrawerOpen(true);
  };

  const columns: ColumnsType<NodeInfo> = [
    { title: '节点名称', dataIndex: 'name', key: 'name', width: 140, ellipsis: true },
    { title: '地址', dataIndex: 'address', key: 'address', width: 180, ellipsis: true },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (s: string) => <Badge status={statusColors[s] ?? 'default'} text={s} /> },
    {
      title: 'CPU', key: 'cpu', width: 160,
      render: (_: unknown, r: NodeInfo) => <Tooltip title={`${r.used.cpu}/${r.capacity.cpu}`}><Progress percent={Math.round(r.used.cpu / r.capacity.cpu * 100)} size="small" /></Tooltip>,
    },
    {
      title: '内存', key: 'mem', width: 160,
      render: (_: unknown, r: NodeInfo) => <Tooltip title={`${(r.used.memory_mb / 1024).toFixed(1)}GB / ${(r.capacity.memory_mb / 1024).toFixed(1)}GB`}><Progress percent={Math.round(r.used.memory_mb / r.capacity.memory_mb * 100)} size="small" /></Tooltip>,
    },
    { title: 'GPU', dataIndex: ['capacity', 'gpu_count'], key: 'gpu', width: 60, render: (c: number) => c ?? 0 },
    { title: '运行中任务', dataIndex: 'tasks_running', key: 'tasks_running', width: 100, align: 'center' as const },
    { title: '最后心跳', dataIndex: 'last_heartbeat', key: 'last_heartbeat', width: 180 },
    {
      title: '操作', key: 'actions', width: 220,
      render: (_: unknown, r: NodeInfo) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => handleViewNode(r)}>详情</Button>
          <Button size="small" onClick={() => handleDrain(r)}>{r.status === 'draining' ? '恢复' : '排空'}</Button>
          <Popconfirm title="确认移除节点？" onConfirm={() => handleDelete(r.node_id)}><Button size="small" danger icon={<DeleteOutlined />} /></Popconfirm>
        </Space>
      ),
    },
  ];

  const onlineCount = nodes.filter((n) => n.status === 'online').length;

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}><Card><Statistic title="在线节点" value={onlineCount} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={8}><Card><Statistic title="总节点数" value={nodes.length} /></Card></Col>
        <Col span={8}><Card><Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button> <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>添加节点</Button></Card></Col>
      </Row>
      <Card title="多节点调度管理">
        <Table rowKey="node_id" columns={columns} dataSource={nodes} loading={loading} pagination={false} size="small" scroll={{ x: 1200 }} />
        <Text type="secondary" style={{ marginTop: 8, display: 'block' }}>Multi-Node Scheduling — 跨节点任务分配与负载均衡</Text>
      </Card>

      <Modal
        title="添加节点"
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false);
          form.resetFields();
        }}
        footer={null}
        width={600}
      >
        <Form form={form} layout="vertical" onFinish={handleAddNode}>
          <Form.Item
            name="node_name"
            label="节点名称"
            rules={[{ required: true, message: '请输入节点名称' }]}
          >
            <Input placeholder="请输入节点名称" />
          </Form.Item>
          
          <Form.Item
            name="address"
            label="地址"
            rules={[{ required: true, message: '请输入节点地址 (host:port)' }]}
            help="格式: hostname:port 或 ip:port"
          >
            <Input placeholder="例如: localhost:8080 或 192.168.1.100:8080" />
          </Form.Item>
          
          <Form.Item 
            name="capacity" 
            label="容量（可选）"
            help='JSON 格式, 例如: {"cpu": 4, "memory_mb": 8192, "gpu_count": 1}'
          >
            <TextArea rows={3} placeholder='可选, JSON 格式: {"cpu": 4, "memory_mb": 8192, "gpu_count": 0}' />
          </Form.Item>
          
          <Form.Item 
            name="labels" 
            label="标签（可选）"
            help='JSON 格式, 例如: {"region": "cn-east", "env": "prod"}'
          >
            <TextArea rows={3} placeholder='可选, JSON 格式: {"region": "cn-east", "env": "prod"}' />
          </Form.Item>
          
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={submitLoading}>
                注册节点
              </Button>
              <Button onClick={() => {
                setModalOpen(false);
                form.resetFields();
              }}>
                取消
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title="节点详情"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={600}
      >
        {selectedNode && (
          <div>
            <Descriptions bordered column={1} size="small">
              <Descriptions.Item label="节点ID">{selectedNode.node_id}</Descriptions.Item>
              <Descriptions.Item label="节点名称">{selectedNode.name}</Descriptions.Item>
              <Descriptions.Item label="地址">{selectedNode.address}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Badge status={statusColors[selectedNode.status] ?? 'default'} text={selectedNode.status} />
              </Descriptions.Item>
              <Descriptions.Item label="CPU 容量">{selectedNode.capacity.cpu}</Descriptions.Item>
              <Descriptions.Item label="CPU 已用">{selectedNode.used.cpu}</Descriptions.Item>
              <Descriptions.Item label="内存容量">{(selectedNode.capacity.memory_mb / 1024).toFixed(1)} GB</Descriptions.Item>
              <Descriptions.Item label="内存已用">{(selectedNode.used.memory_mb / 1024).toFixed(1)} GB</Descriptions.Item>
              <Descriptions.Item label="GPU 数量">{selectedNode.capacity.gpu_count}</Descriptions.Item>
              <Descriptions.Item label="运行中任务">{selectedNode.tasks_running}</Descriptions.Item>
              <Descriptions.Item label="标签">
                {Object.entries(selectedNode.labels).map(([key, value]) => (
                  <Tag key={key} style={{ marginBottom: 4 }}>{key}: {value}</Tag>
                ))}
              </Descriptions.Item>
              <Descriptions.Item label="最后心跳">{selectedNode.last_heartbeat}</Descriptions.Item>
            </Descriptions>
          </div>
        )}
      </Drawer>
    </div>
  );
}
