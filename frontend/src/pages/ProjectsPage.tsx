/**
 * ProjectsPage - 项目管理 + Issue 跟踪页面
 * 合并 Projects 和 Issues 两个视图，用 Tabs 切换
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Tabs, Table, Button, Tag, Card, Space, message, Popconfirm, Typography, Tooltip, Modal, Form, Input, Select } from 'antd';
import { ReloadOutlined, PlusOutlined, DeleteOutlined, EyeOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  fetchProjects, fetchProject, createProject, deleteProject,
  fetchIssues, createIssue, updateIssue, deleteIssue,
  type Project, type Issue, type IssueStatus, type IssuePriority, type IssueType,
} from '../api/projects';

const { Text, Paragraph } = Typography;

const statusColors: Record<IssueStatus, string> = { open: 'blue', in_progress: 'processing', review: 'purple', done: 'green', closed: 'default' };
const priorityColors: Record<IssuePriority, string> = { critical: 'red', high: 'orange', medium: 'blue', low: 'default' };
const typeColors: Record<IssueType, string> = { bug: 'red', feature: 'green', task: 'blue', epic: 'purple' };

// ===== Projects Tab =====
function ProjectsTab() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try { setProjects(await fetchProjects()); } catch (e: unknown) { message.error(`加载失败: ${(e as Error).message}`); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      await createProject(values);
      message.success('项目已创建');
      setModalOpen(false);
      load();
    } catch (e: unknown) { message.error(`创建失败: ${(e as Error).message}`); }
  };

  const handleDelete = async (projectId: string) => {
    try { await deleteProject(projectId); message.success('项目已删除'); load(); } catch (e: unknown) { message.error(`删除失败: ${(e as Error).message}`); }
  };

  const columns: ColumnsType<Project> = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 160, render: (n: string, r: Project) => <a onClick={async () => { const d = await fetchProject(r.project_id); Modal.info({ title: d.name, content: <pre style={{ maxHeight: 300 }}>{JSON.stringify(d, null, 2)}</pre> }); }}>{n}</a> },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    { title: '状态', dataIndex: 'status', key: 'status', width: 80, render: (s: string) => <Tag>{s}</Tag> },
    { title: '成员数', dataIndex: 'member_ids', key: 'members', width: 80, render: (ids: string[]) => ids?.length ?? 0 },
    { title: '标签', dataIndex: 'tags', key: 'tags', width: 140, render: (tags: string[]) => tags?.map((t) => <Tag key={t}>{t}</Tag>) },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
    {
      title: '操作', key: 'actions', width: 120,
      render: (_: unknown, r: Project) => (
        <Popconfirm title="确认删除？" onConfirm={() => handleDelete(r.project_id)}><Tooltip title="删除"><Button size="small" danger icon={<DeleteOutlined />} /></Tooltip></Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <Card title="项目管理" extra={<Space><Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setModalOpen(true); }}>新建项目</Button></Space>}>
        <Table rowKey="project_id" columns={columns} dataSource={projects} loading={loading} pagination={{ pageSize: 20 }} size="small" />
      </Card>
      <Modal title="新建项目" open={modalOpen} onOk={handleCreate} onCancel={() => setModalOpen(false)} destroyOnHidden>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="项目名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="tags" label="标签"><Select mode="tags" placeholder="输入标签" /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ===== Issues Tab =====
function IssuesTab() {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();
  const [selectedProject, setSelectedProject] = useState<string | undefined>(undefined);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = await fetchProjects();
      setProjects(p);
      if (p.length > 0) {
        const pid = selectedProject || p[0].project_id;
        setSelectedProject(pid);
        setIssues(await fetchIssues(pid));
      }
    } catch (e: unknown) { message.error(`加载失败: ${(e as Error).message}`); } finally { setLoading(false); }
  }, [selectedProject]);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    if (!selectedProject) { message.warning('请先选择项目'); return; }
    try {
      const values = await form.validateFields();
      await createIssue(selectedProject, values);
      message.success('Issue 已创建');
      setModalOpen(false);
      load();
    } catch (e: unknown) { message.error(`创建失败: ${(e as Error).message}`); }
  };

  const handleDelete = async (issueId: string) => {
    try { await deleteIssue(issueId); message.success('Issue 已删除'); load(); } catch (e: unknown) { message.error(`删除失败: ${(e as Error).message}`); }
  };

  const columns: ColumnsType<Issue> = [
    { title: '标题', dataIndex: 'title', key: 'title', width: 200, ellipsis: true },
    { title: '类型', dataIndex: 'type', key: 'type', width: 80, render: (t: IssueType) => <Tag color={typeColors[t]}>{t}</Tag> },
    { title: '优先级', dataIndex: 'priority', key: 'priority', width: 80, render: (p: IssuePriority) => <Tag color={priorityColors[p]}>{p}</Tag> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (s: IssueStatus) => <Tag color={statusColors[s]}>{s}</Tag> },
    { title: '标签', dataIndex: 'labels', key: 'labels', width: 140, render: (labels: string[]) => labels?.map((l) => <Tag key={l}>{l}</Tag>) },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 180 },
    {
      title: '操作', key: 'actions', width: 120,
      render: (_: unknown, r: Issue) => (
        <Popconfirm title="确认删除？" onConfirm={() => handleDelete(r.issue_id)}><Tooltip title="删除"><Button size="small" danger icon={<DeleteOutlined />} /></Tooltip></Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <Card
        title="Issue 跟踪"
        extra={
          <Space>
            <Select placeholder="选择项目" style={{ width: 180 }} value={selectedProject} onChange={(v) => { setSelectedProject(v); fetchIssues(v).then(setIssues).catch(() => {}); }} loading={loading}>
              {projects.map((p) => <Select.Option key={p.project_id} value={p.project_id}>{p.name}</Select.Option>)}
            </Select>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setModalOpen(true); }} disabled={!selectedProject}>新建 Issue</Button>
          </Space>
        }
      >
        <Table rowKey="issue_id" columns={columns} dataSource={issues} loading={loading} pagination={{ pageSize: 20 }} size="small" />
      </Card>
      <Modal title="新建 Issue" open={modalOpen} onOk={handleCreate} onCancel={() => setModalOpen(false)} destroyOnHidden>
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="标题" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="type" label="类型" initialValue="task"><Select><Select.Option value="bug">Bug</Select.Option><Select.Option value="feature">Feature</Select.Option><Select.Option value="task">Task</Select.Option><Select.Option value="epic">Epic</Select.Option></Select></Form.Item>
          <Form.Item name="priority" label="优先级" initialValue="medium"><Select><Select.Option value="critical">Critical</Select.Option><Select.Option value="high">High</Select.Option><Select.Option value="medium">Medium</Select.Option><Select.Option value="low">Low</Select.Option></Select></Form.Item>
          <Form.Item name="labels" label="标签"><Select mode="tags" /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ===== Main Page =====
const tabItems = [
  { key: 'projects', label: '项目管理', children: <ProjectsTab /> },
  { key: 'issues', label: 'Issue 跟踪', children: <IssuesTab /> },
];

export default function ProjectsPage() {
  return (
    <div>
      <Paragraph type="secondary" style={{ display: 'block', marginBottom: 16 }}>项目管理与 Issue 跟踪 — 需求管理、Bug 追踪、任务分配</Paragraph>
      <Tabs type="card" items={tabItems} />
    </div>
  );
}
