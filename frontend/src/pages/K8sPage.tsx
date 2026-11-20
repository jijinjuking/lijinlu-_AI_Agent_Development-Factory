/**
 * K8sPage - K8s Job 调度管理页面
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Table, Button, Tag, Card, Space, message, Popconfirm, Badge, Typography, Tooltip, Form, Input, Modal } from 'antd';
import { ReloadOutlined, PlusOutlined, DeleteOutlined, StopOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { fetchK8sJobs, cancelK8sJob, deleteK8sJob, createK8sJob, type K8sJob } from '../api/k8s';

const { Text } = Typography;
const { TextArea } = Input;

const statusColors: Record<string, 'default' | 'processing' | 'success' | 'error' | 'warning'> = {
  pending: 'default', running: 'processing', completed: 'success', failed: 'error', canceled: 'warning',
};

export default function K8sPage() {
  const [jobs, setJobs] = useState<K8sJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try { setJobs(await fetchK8sJobs()); } catch (e: unknown) { message.error(`加载失败: ${(e as Error).message}`); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreateJob = async (values: any) => {
    try {
      // 解析 env 文本为对象
      let envVars: Record<string, string> = {};
      if (values.env) {
        try {
          // 支持 JSON 格式或 KEY=VALUE 格式
          if (values.env.trim().startsWith('{')) {
            envVars = JSON.parse(values.env);
          } else {
            // 解析 KEY=VALUE 格式，每行一个
            envVars = {};
            values.env.split('\n').forEach((line: string) => {
              const idx = line.indexOf('=');
              if (idx > 0) {
                const key = line.substring(0, idx).trim();
                const val = line.substring(idx + 1).trim();
                if (key) envVars[key] = val;
              }
            });
          }
        } catch (e) {
          message.error('环境变量格式错误，请使用 JSON 或 KEY=VALUE 格式');
          return;
        }
      }

      // 解析 command 为数组
      const command = values.command ? values.command.split('\n').filter((c: string) => c.trim()) : [];

      await createK8sJob({
        task_id: values.name,
        config: {
          job_name: values.name,
          namespace: values.namespace,
          image: values.image,
          command: command,
          env_vars: envVars,
        },
      });

      message.success('任务创建成功');
      setCreateModalOpen(false);
      form.resetFields();
      load(); // 重新加载任务列表
    } catch (e: unknown) {
      message.error(`创建失败: ${(e as Error).message}`);
    }
  };

  const columns: ColumnsType<K8sJob> = [
    { title: '任务名称', dataIndex: 'name', key: 'name', width: 160, ellipsis: true },
    { title: '命名空间', dataIndex: 'namespace', key: 'namespace', width: 120 },
    { title: '镜像', dataIndex: 'image', key: 'image', width: 200, ellipsis: true },
    { title: '节点', dataIndex: 'node_name', key: 'node_name', width: 120, render: (n?: string) => n || '-' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (s: string) => <Badge status={statusColors[s] ?? 'default'} text={s} /> },
    { title: '退出码', dataIndex: 'exit_code', key: 'exit_code', width: 80, render: (c?: number) => c ?? '-' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
    {
      title: '操作', key: 'actions', width: 140,
      render: (_: unknown, r: K8sJob) => (
        <Space>
          {r.status === 'running' && <Popconfirm title="确认取消？" onConfirm={async () => { await cancelK8sJob(r.job_id); load(); }}><Tooltip title="取消"><Button size="small" danger icon={<StopOutlined />} /></Tooltip></Popconfirm>}
          <Popconfirm title="确认删除？" onConfirm={async () => { await deleteK8sJob(r.job_id); load(); }}><Tooltip title="删除"><Button size="small" danger icon={<DeleteOutlined />} /></Tooltip></Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card 
        title="K8s Job 调度管理" 
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalOpen(true)}>创建任务</Button>
          </Space>
        }
      >
        <Table 
          rowKey="job_id" 
          columns={columns} 
          dataSource={jobs} 
          loading={loading} 
          pagination={{ pageSize: 20 }} 
          size="small" 
          scroll={{ x: 1100 }} 
        />
        <Text type="secondary" style={{ marginTop: 8, display: 'block' }}>K8s Job Scheduler — 分布式任务调度到 K8s 集群</Text>
      </Card>

      <Modal
        title="创建 K8s 任务"
        open={createModalOpen}
        onCancel={() => {
          setCreateModalOpen(false);
          form.resetFields();
        }}
        footer={null}
        width={600}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleCreateJob}
          initialValues={{
            namespace: 'default',
          }}
        >
          <Form.Item
            label="任务名称"
            name="name"
            rules={[{ required: true, message: '请输入任务名称' }]}
          >
            <Input placeholder="请输入任务名称" />
          </Form.Item>

          <Form.Item
            label="命名空间"
            name="namespace"
            rules={[{ required: true, message: '请输入命名空间' }]}
          >
            <Input placeholder="default" />
          </Form.Item>

          <Form.Item
            label="镜像"
            name="image"
            rules={[{ required: true, message: '请输入镜像地址' }]}
          >
            <Input placeholder="例如: nginx:latest" />
          </Form.Item>

          <Form.Item
            label="命令"
            name="command"
            help="每行一个命令参数"
          >
            <TextArea 
              rows={3} 
              placeholder="例如:&#10;python&#10;train.py&#10;--epochs 10" 
            />
          </Form.Item>

          <Form.Item
            label="环境变量"
            name="env"
            help="支持 JSON 格式或 KEY=VALUE 格式（每行一个）"
          >
            <TextArea 
              rows={4} 
              placeholder='例如 JSON: {"ENV": "prod", "DEBUG": "true"}&#10;或 KEY=VALUE:&#10;ENV=prod&#10;DEBUG=true' 
            />
          </Form.Item>

          <Form.Item
            label="节点名称（可选）"
            name="node_name"
          >
            <Input placeholder="指定运行节点（可选）" />
          </Form.Item>

          <Form.Item>
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button onClick={() => {
                setCreateModalOpen(false);
                form.resetFields();
              }}>
                取消
              </Button>
              <Button type="primary" htmlType="submit">
                创建
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
