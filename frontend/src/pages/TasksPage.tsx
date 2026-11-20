/**
 * TasksPage - 任务管理页面
 * 覆盖: Kanban 看板 + 任务列表 + 任务执行监控
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Tag,
  Space,
  Card,
  Statistic,
  Row,
  Col,
  message,
  Popconfirm,
  Tooltip,
  Badge,
} from 'antd';
import {
  PlusOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  StopOutlined,
  DeleteOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  fetchTaskList,
  fetchKanbanBoard,
  createTask,
  updateTask,
  deleteTask,
  executeTask,
  cancelTask,
  type Task,
} from '../api/tasks';

const statusColors: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  completed: 'success',
  failed: 'error',
  canceling: 'warning',
};

const priorityColors: Record<number, string> = {
  1: 'red',
  3: 'orange',
  5: 'blue',
  7: 'green',
  10: 'gray',
};

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [form] = Form.useForm();

  const loadTasks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchTaskList();
      setTasks(data);
    } catch (e: unknown) {
      message.error(`加载任务失败: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  const handleCreate = () => {
    setEditingTask(null);
    form.resetFields();
    setModalOpen(true);
  };

  const handleEdit = (task: Task) => {
    setEditingTask(task);
    form.setFieldsValue(task);
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      if (editingTask) {
        await updateTask(editingTask.id, values);
        message.success('任务已更新');
      } else {
        await createTask(values);
        message.success('任务已创建');
      }
      setModalOpen(false);
      loadTasks();
    } catch (e: unknown) {
      message.error(`操作失败: ${(e as Error).message}`);
    }
  };

  const handleDelete = async (taskId: string) => {
    try {
      await deleteTask(taskId);
      message.success('任务已删除');
      loadTasks();
    } catch (e: unknown) {
      message.error(`删除失败: ${(e as Error).message}`);
    }
  };

  const handleExecute = async (taskId: string) => {
    try {
      await executeTask(taskId);
      message.success('任务已提交执行');
      loadTasks();
    } catch (e: unknown) {
      message.error(`执行失败: ${(e as Error).message}`);
    }
  };

  const handleCancel = async (taskId: string) => {
    try {
      await cancelTask(taskId);
      message.success('任务已取消');
      loadTasks();
    } catch (e: unknown) {
      message.error(`取消失败: ${(e as Error).message}`);
    }
  };

  // ── 表格列定义（memoize） ──
  const columns: ColumnsType<Task> = useMemo(() => [
    {
      title: '任务名称',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (text: string, record: Task) => (
        <Tooltip title={record.goal_description || text} key={`name-${record.id}`}>
          <a onClick={() => handleEdit(record)}>{text || record.goal_description}</a>
        </Tooltip>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string, record: Task) => (
        <Badge
          key={`status-${record.id}`}
          status={statusColors[status] as 'default' | 'processing' | 'success' | 'error' | 'warning'}
          text={status}
        />
      ),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 100,
      render: (p: number, record: Task) => <Tag color={priorityColors[p] ?? 'blue'} key={`pri-${record.id}`}>{p}</Tag>,
    },
    {
      title: 'Agent',
      dataIndex: 'agentName',
      key: 'agentName',
      width: 200,
      ellipsis: true,
      render: (name: string, record: Task) => name || record.agentId || '-',
    },
    {
      title: '创建时间',
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 180,
      render: (val: string) => val ? new Date(val).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 240,
      render: (_: unknown, record: Task) => (
        <Space key={`actions-${record.id}`}>
          {record.status === 'pending' && (
            <Tooltip title="执行" key={`execute-${record.id}`}>
              <Button
                type="link"
                size="small"
                icon={<PlayCircleOutlined />}
                onClick={() => handleExecute(record.id)}
              />
            </Tooltip>
          )}
          {record.status === 'running' && (
            <Tooltip title="取消" key={`cancel-${record.id}`}>
              <Button
                type="link"
                size="small"
                danger
                icon={<StopOutlined />}
                onClick={() => handleCancel(record.id)}
              />
            </Tooltip>
          )}
          <Tooltip title="编辑" key={`edit-${record.id}`}>
            <Button
              type="link"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => handleEdit(record)}
            />
          </Tooltip>
          <Popconfirm
            key={`delete-${record.id}`}
            title="确认删除此任务？"
            onConfirm={() => handleDelete(record.id)}
          >
            <Tooltip title="删除">
              <Button type="link" size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ], []);

  const stats = useMemo(() => ({
    total: tasks.length,
    running: tasks.filter((t) => t.status === 'running').length,
    completed: tasks.filter((t) => t.status === 'completed').length,
    failed: tasks.filter((t) => t.status === 'failed').length,
  }), [tasks]);

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card><Statistic title="总任务" value={stats.total} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="执行中" value={stats.running} styles={{ content: { color: '#1890ff' } }} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="已完成" value={stats.completed} styles={{ content: { color: '#52c41a' } }} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="失败" value={stats.failed} styles={{ content: { color: '#ff4d4f' } }} /></Card>
        </Col>
      </Row>

      <Card
        title="任务管理"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={loadTasks} loading={loading}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
              新建任务
            </Button>
          </Space>
        }
      >
        <Table
          key={`tasks-table-${tasks.length}`}
          rowKey={(record) => record.id}
          columns={columns}
          dataSource={tasks}
          loading={loading}
          pagination={{ pageSize: 20 }}
          locale={{ emptyText: <div key="tasks-empty">暂无任务</div> }}
        />
      </Card>

      <Modal
        title={editingTask ? '编辑任务' : '新建任务'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        destroyOnHidden
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}>
            <Input placeholder="请输入任务名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="请输入任务描述" />
          </Form.Item>
          <Form.Item name="agent_id" label="Agent" rules={[{ required: true, message: '请选择 Agent' }]}>
            <Input placeholder="Agent ID" />
          </Form.Item>
          <Form.Item name="priority" label="优先级" initialValue={5}>
            <Select>
              <Select.Option key="pri-1" value={1}>1 - 紧急</Select.Option>
              <Select.Option key="pri-3" value={3}>3 - 高</Select.Option>
              <Select.Option key="pri-5" value={5}>5 - 中</Select.Option>
              <Select.Option key="pri-7" value={7}>7 - 低</Select.Option>
              <Select.Option key="pri-10" value={10}>10 - 最低</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="initial_state" label="初始状态 (JSON)">
            <Input.TextArea rows={4} placeholder='{"key": "value"}' />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
