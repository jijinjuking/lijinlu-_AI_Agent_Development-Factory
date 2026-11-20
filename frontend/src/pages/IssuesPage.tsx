/**
 * IssuesPage - Issue 列表页面
 *
 * 功能:
 * - 按 Project / Status / Priority 筛选
 * - 新建 Issue
 * - 状态快速切换
 * - 点击进入详情页
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  Table, Button, Modal, Form, Input, Select, Tag, Space, Card,
  Row, Col, App, Popconfirm, Tooltip, Badge, Upload, Typography,
} from 'antd';
import {
  PlusOutlined, ReloadOutlined, DeleteOutlined, EyeOutlined,
  ApartmentOutlined, SendOutlined, BugOutlined, UploadOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';
import * as issuesApi from '../api/issues';
import type { Issue, IssueStatus, IssuePriority } from '../api/issues';
import { useProjectsStore } from '../stores/projectsStore';

const statusMap: Record<IssueStatus, { label: string; color: string }> = {
  open: { label: '待处理', color: 'blue' },
  in_progress: { label: '进行中', color: 'processing' },
  pending_review: { label: '待审核', color: 'orange' },
  resolved: { label: '已解决', color: 'green' },
  closed: { label: '已关闭', color: 'default' },
};

const priorityMap: Record<IssuePriority, { label: string; color: string }> = {
  critical: { label: '严重', color: 'red' },
  high: { label: '高', color: 'orange' },
  medium: { label: '中', color: 'blue' },
  low: { label: '低', color: 'green' },
};

export default function IssuesPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [issues, setIssues] = useState<Issue[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();

  // 筛选
  const [filterProject, setFilterProject] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterPriority, setFilterPriority] = useState('');

  // 获取项目列表
  const projects = useProjectsStore((s) => s.projects);
  const loadProjects = useProjectsStore((s) => s.loadProjects);
  useEffect(() => { loadProjects(); }, [loadProjects]);

  // 加载数据
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await issuesApi.fetchIssues({
        project_id: filterProject || undefined,
        status: (filterStatus || undefined) as IssueStatus | undefined,
        priority: (filterPriority || undefined) as IssuePriority | undefined,
      });
      setIssues(data);
    } catch {
      message.error('加载 Issue 失败');
    } finally {
      setLoading(false);
    }
  }, [filterProject, filterStatus, filterPriority]);

  useEffect(() => { load(); }, [load]);

  // 创建 Issue
  const handleCreate = async (values: Record<string, unknown>) => {
    setCreating(true);
    try {
      const newIssue = await issuesApi.createIssue(values as unknown as {
        project_id: string;
        title: string;
        description?: string;
        priority?: IssuePriority;
      });
      message.success('创建成功');

      // 上传暂存的附件
      if (pendingFiles.length > 0) {
        for (const file of pendingFiles) {
          try {
            await issuesApi.uploadAttachment(newIssue.issue_id, file);
          } catch (e: any) {
            message.warning(`附件 ${file.name} 上传失败: ${e.message}`);
          }
        }
        setPendingFiles([]);
      }

      setCreateOpen(false);
      form.resetFields();
      load();
    } catch {
      message.error('创建失败');
    } finally {
      setCreating(false);
    }
  };

  // 切换状态
  const handleStatusChange = async (issueId: string, status: IssueStatus) => {
    try {
      await issuesApi.updateIssue(issueId, { status });
      message.success('状态已更新');
      load();
    } catch {
      message.error('更新失败');
    }
  };

  // 删除
  const handleDelete = async (issueId: string) => {
    try {
      await issuesApi.deleteIssue(issueId);
      message.success('已删除');
      load();
    } catch {
      message.error('删除失败');
    }
  };

  // 快速分解
  const handleDecompose = async (issueId: string) => {
    try {
      await issuesApi.decomposeIssue(issueId);
      message.success('分解完成');
      load();
    } catch {
      message.error('分解失败');
    }
  };

  // 快速派发
  const handleDispatch = async (issueId: string) => {
    try {
      await issuesApi.dispatchIssue(issueId);
      message.success('派发完成');
      load();
    } catch {
      message.error('派发失败');
    }
  };

  // 表格列定义
  const columns: ColumnsType<Issue> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      render: (title: string, record: Issue) => (
        <a onClick={() => navigate(`/issues/${record.issue_id}`)} style={{ fontWeight: 500 }}>
          <BugOutlined style={{ marginRight: 6, color: '#8c8c8c' }} />
          {title}
        </a>
      ),
    },
    {
      title: '项目',
      dataIndex: 'project_id',
      key: 'project',
      width: 140,
      render: (pid: string) => {
        const proj = projects.find((p) => p.project_id === pid);
        return proj?.name ?? pid?.substring(0, 8) ?? '-';
      },
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 90,
      render: (p: IssuePriority) => (
        <Tag color={priorityMap[p]?.color}>{priorityMap[p]?.label ?? p}</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (s: IssueStatus) => (
        <Badge status={statusMap[s]?.color === 'processing' ? 'processing' : 'default' as 'success' | 'error' | 'warning'}
               text={statusMap[s]?.label ?? s}
        />
      ),
    },
    {
      title: '任务进度',
      key: 'progress',
      width: 120,
      render: (_: unknown, record: Issue) => {
        const total = record.task_count ?? 0;
        const done = record.completed_task_count ?? 0;
        if (total === 0) return <span style={{ color: '#8c8c8c' }}>-</span>;
        return <span>{done}/{total} ({total > 0 ? Math.round(done / total * 100) : 0}%)</span>;
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 280,
      render: (_: unknown, record: Issue) => (
        <Space size="small" wrap>
          <Tooltip title="查看详情">
            <Button size="small" icon={<EyeOutlined />}
              onClick={() => navigate(`/issues/${record.issue_id}`)} />
          </Tooltip>
          {record.status === 'open' && (
            <>
              <Tooltip title="分解为子任务">
                <Button size="small" icon={<ApartmentOutlined />}
                  onClick={() => handleDecompose(record.issue_id)} />
              </Tooltip>
              <Select size="small" value={record.status} style={{ width: 90 }}
                onChange={(v) => handleStatusChange(record.issue_id, v)}>
                <Select.Option value="in_progress">开始处理</Select.Option>
                <Select.Option value="closed">关闭</Select.Option>
              </Select>
            </>
          )}
          {record.status === 'in_progress' && (
            <>
              <Tooltip title="派发任务">
                <Button size="small" icon={<SendOutlined />}
                  onClick={() => handleDispatch(record.issue_id)} />
              </Tooltip>
              <Select size="small" value={record.status} style={{ width: 90 }}
                onChange={(v) => handleStatusChange(record.issue_id, v)}>
                <Select.Option value="pending_review">提交审核</Select.Option>
                <Select.Option value="resolved">标记解决</Select.Option>
              </Select>
            </>
          )}
          {record.status === 'pending_review' && (
            <Select size="small" value={record.status} style={{ width: 90 }}
              onChange={(v) => handleStatusChange(record.issue_id, v)}>
              <Select.Option value="resolved">通过</Select.Option>
              <Select.Option value="in_progress">驳回</Select.Option>
            </Select>
          )}
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(record.issue_id)}>
            <Tooltip title="删除">
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {/* 标题栏 */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h2 style={{ margin: 0 }}>
            <BugOutlined style={{ marginRight: 8 }} />
            Issue 跟踪
          </h2>
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />}
              onClick={() => setCreateOpen(true)}>新建 Issue</Button>
          </Space>
        </Col>
      </Row>

      {/* 筛选卡片 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col>
            <span style={{ marginRight: 8 }}>项目:</span>
            <Select value={filterProject} onChange={setFilterProject}
              allowClear placeholder="全部" style={{ width: 160 }}>
              {projects.map((p) => (
                <Select.Option key={p.project_id} value={p.project_id}>{p.name}</Select.Option>
              ))}
            </Select>
          </Col>
          <Col>
            <span style={{ marginRight: 8 }}>状态:</span>
            <Select value={filterStatus} onChange={setFilterStatus}
              allowClear placeholder="全部" style={{ width: 120 }}>
              {Object.entries(statusMap).map(([k, v]) => (
                <Select.Option key={k} value={k}>{v.label}</Select.Option>
              ))}
            </Select>
          </Col>
          <Col>
            <span style={{ marginRight: 8 }}>优先级:</span>
            <Select value={filterPriority} onChange={setFilterPriority}
              allowClear placeholder="全部" style={{ width: 100 }}>
              {Object.entries(priorityMap).map(([k, v]) => (
                <Select.Option key={k} value={k}>{v.label}</Select.Option>
              ))}
            </Select>
          </Col>
        </Row>
      </Card>

      {/* 列表 */}
      <Table<Issue>
        dataSource={issues}
        columns={columns}
        rowKey={(r) => r.issue_id}
        loading={loading}
        pagination={{ pageSize: 20, showSizeChanger: true }}
        locale={{ emptyText: '暂无 Issue，点击"新建 Issue"创建' }}
      />

      {/* 新建 Modal */}
      <Modal title="新建 Issue" open={createOpen}
        onCancel={() => { setCreateOpen(false); form.resetFields(); setPendingFiles([]); }}
        onOk={() => form.submit()} okText="创建" confirmLoading={creating}>
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item name="project_id" label="所属项目" rules={[{ required: true, message: '请选择项目' }]}>
            <Select placeholder="选择项目">
              {projects.map((p) => (
                <Select.Option key={p.project_id} value={p.project_id}>{p.name}</Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="Issue 标题" maxLength={255} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={4} placeholder="描述问题或需求" />
          </Form.Item>
          <Form.Item name="priority" label="优先级" initialValue="medium">
            <Select>
              <Select.Option value="critical">严重</Select.Option>
              <Select.Option value="high">高</Select.Option>
              <Select.Option value="medium">中</Select.Option>
              <Select.Option value="low">低</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item label="附件">
            <Upload
              accept=".docx,.pdf,.md,.txt"
              multiple
              fileList={pendingFiles.map((f) => ({
                uid: f.name,
                name: f.name,
                size: f.size,
                status: 'done' as const,
              }))}
              beforeUpload={(file) => {
                setPendingFiles((prev) => [...prev, file]);
                return false;
              }}
              onRemove={(file) => {
                setPendingFiles((prev) => prev.filter((f) => f.name !== file.name));
              }}
            >
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
            <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
              支持 DOCX、PDF、MD、TXT，可多选，单个文件不超过 10MB
            </Typography.Text>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
