/**
 * IssueDetailPage - Issue 详情页面
 *
 * 功能:
 * - Issue 基本信息展示与编辑
 * - 任务树可视化（递归树形组件）
 * - 分解 / 派发操作
 * - 评论列表
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, Button, Tag, Space, Descriptions, App, Spin, Tree,
  Modal, Form, Input, Select, Row, Col, Timeline, Empty, Popconfirm,
  Upload, List, Typography,
} from 'antd';
import {
  ArrowLeftOutlined, ApartmentOutlined, SendOutlined,
  ReloadOutlined, EditOutlined, CommentOutlined, CaretRightOutlined,
  PaperClipOutlined, DownloadOutlined, DeleteOutlined, UploadOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import * as issuesApi from '../api/issues';
import type { Issue, IssueStatus, IssuePriority, TaskTreeNode, Attachment } from '../api/issues';
import { useIssuesStore } from '../stores/issuesStore';

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

const roleColors: Record<string, string> = {
  developer: '#1677ff', reviewer: '#fa8c16', tester: '#52c41a',
  architect: '#722ed1', operator: '#13c2c2',
};

/** 任务树节点渲染 */
function TaskTreeView({ nodes }: { nodes: TaskTreeNode[] }) {
  if (!nodes || nodes.length === 0) {
    return <Empty description="暂无子任务" />;
  }

  const treeData = nodes.map((n) => convertNode(n));

  function convertNode(node: TaskTreeNode): Record<string, unknown> {
    return {
      key: node.id,
      title: (
        <Space split="small">
          <Tag color={roleColors[node.role] || '#8c8c8c'} style={{ fontSize: 11 }}>
            {node.role || 'task'}
          </Tag>
          <span>{node.title || node.name}</span>
          {node.status && (
            <Tag style={{ fontSize: 10 }}>{node.status}</Tag>
          )}
          {node.agent_name && (
            <span style={{ color: '#8c8c8c', fontSize: 12 }}>@{node.agent_name}</span>
          )}
        </Space>
      ),
      children: node.children?.map((c) => convertNode(c)) ?? [],
    } as Record<string, unknown>;
  }

  return (
    <Tree
      treeData={treeData as any}
      defaultExpandAll
      showLine={{ showLeafIcon: false }}
      style={{ marginTop: 8 }}
    />
  );
}

/** 评论列表 */
function CommentList({ issueId }: { issueId: string }) {
  const { comments, loadComments, addComment } = useIssuesStore();
  const [txt, setTxt] = useState('');

  useEffect(() => { loadComments(issueId); }, [issueId, loadComments]);

  const handleAdd = async () => {
    if (!txt.trim()) return;
    await addComment(issueId, txt.trim());
    setTxt('');
  };

  return (
    <Card title={<><CommentOutlined /> 评论</>} size="small">
      {comments.length === 0 ? (
        <Empty description="暂无评论" />
      ) : (
        <Timeline
          items={comments.map((c) => ({
            children: (
              <div>
                <div style={{ color: '#8c8c8c', fontSize: 12, marginBottom: 4 }}>
                  {c.author_id ?? '未知'} · {new Date(c.created_at).toLocaleString('zh-CN')}
                </div>
                <div>{c.content}</div>
              </div>
            ),
          }))}
        />
      )}
      <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
        <Input.TextArea rows={2} value={txt} onChange={(e) => setTxt(e.target.value)}
          placeholder="添加评论..." />
        <Button type="primary" onClick={handleAdd} disabled={!txt.trim()}
          style={{ alignSelf: 'flex-end' }}>发送</Button>
      </div>
    </Card>
  );
}

export default function IssueDetailPage() {
  const { message } = App.useApp();
  const { issueId } = useParams<{ issueId: string }>();
  const navigate = useNavigate();

  const [issue, setIssue] = useState<Issue | null>(null);
  const [taskTree, setTaskTree] = useState<TaskTreeNode[]>([]);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [decomposing, setDecomposing] = useState(false);
  const [dispatching, setDispatching] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    if (!issueId) return;
    setLoading(true);
    try {
      const [iss, tree, atts] = await Promise.all([
        issuesApi.fetchIssue(issueId),
        issuesApi.fetchTaskTree(issueId).catch(() => [] as TaskTreeNode[]),
        issuesApi.fetchAttachments(issueId).catch(() => [] as Attachment[]),
      ]);
      setIssue(iss);
      setTaskTree(tree);
      setAttachments(atts);
    } catch {
      message.error('加载失败');
    } finally {
      setLoading(false);
    }
  }, [issueId]);

  useEffect(() => { load(); }, [load]);

  const handleDecompose = async () => {
    if (!issueId) return;
    setDecomposing(true);
    try {
      const result = await issuesApi.decomposeIssue(issueId);
      setIssue(result.issue);
      message.success('分解完成');
      // 直接使用返回的任务树，避免重新请求
      if (result.taskTree?.nodes) {
        setTaskTree(result.taskTree.nodes);
      } else {
        const tree = await issuesApi.fetchTaskTree(issueId).catch(() => [] as TaskTreeNode[]);
        setTaskTree(tree);
      }
    } catch {
      message.error('分解失败');
    } finally {
      setDecomposing(false);
    }
  };

  const handleDispatch = async () => {
    if (!issueId) return;
    setDispatching(true);
    try {
      await issuesApi.dispatchIssue(issueId);
      message.success('派发完成');
      load();
    } catch {
      message.error('派发失败');
    } finally {
      setDispatching(false);
    }
  };

  const handleEdit = async (values: Record<string, unknown>) => {
    if (!issueId) return;
    try {
      const updated = await issuesApi.updateIssue(issueId, values as Record<string, string>);
      setIssue(updated);
      message.success('已更新');
      setEditOpen(false);
    } catch {
      message.error('更新失败');
    }
  };

  const handleStatusChange = async (status: IssueStatus) => {
    if (!issueId) return;
    try {
      const updated = await issuesApi.updateIssue(issueId, { status });
      setIssue(updated);
      message.success('状态已更新');
    } catch {
      message.error('更新失败');
    }
  };

  // 附件处理 — 支持批量上传
  const handleBatchUpload = async (files: File[]) => {
    if (!issueId || files.length === 0) return;
    setUploading(true);
    let successCount = 0;
    let failCount = 0;
    for (const file of files) {
      try {
        await issuesApi.uploadAttachment(issueId, file);
        successCount++;
      } catch (_e: any) {
        failCount++;
      }
    }
    try {
      const atts = await issuesApi.fetchAttachments(issueId);
      setAttachments(atts);
    } catch { /* ignore refresh error */ }
    setUploading(false);
    if (failCount === 0) {
      message.success(`全部上传成功（${successCount} 个文件）`);
    } else {
      message.warning(`上传完成：成功 ${successCount} 个，失败 ${failCount} 个`);
    }
  };

  const handleDeleteAttachment = async (attId: string) => {
    if (!issueId) return;
    try {
      await issuesApi.deleteAttachment(issueId, attId);
      message.success('删除成功');
      setAttachments((prev) => prev.filter((a) => a.id !== attId));
    } catch {
      message.error('删除失败');
    }
  };

  if (loading) {
    return <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 80 }}><Spin size="large" /></div>;
  }

  if (!issue) {
    return <div style={{ padding: 24 }}><Empty description="Issue 不存在" /></div>;
  }

  const statusInfo = statusMap[issue.status];
  const priorityInfo = priorityMap[issue.priority];

  return (
    <div style={{ padding: 24 }}>
      {/* 返回按钮 */}
      <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/issues')}
        style={{ marginBottom: 16, paddingLeft: 0 }}>
        返回列表
      </Button>

      <Row gutter={24}>
        {/* 左侧: Issue 详情 */}
        <Col xs={24} lg={14}>
          <Card
            title={
              <Space>
                <Tag color={priorityInfo.color}>{priorityInfo.label}</Tag>
                <span style={{ fontSize: 18, fontWeight: 600 }}>{issue.title}</span>
              </Space>
            }
            extra={
              <Space>
                <Button icon={<EditOutlined />} onClick={() => {
                  form.setFieldsValue(issue);
                  setEditOpen(true);
                }}>编辑</Button>
                <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
              </Space>
            }
          >
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="状态">
                <Tag color={statusInfo.color}>{statusInfo.label}</Tag>
                <Select size="small" value={issue.status}
                  onChange={(v) => handleStatusChange(v)} style={{ width: 100, marginLeft: 8 }}>
                  {Object.entries(statusMap).map(([k, v]) => (
                    <Select.Option key={k} value={k}>{v.label}</Select.Option>
                  ))}
                </Select>
              </Descriptions.Item>
              <Descriptions.Item label="项目">{issue.project_id?.substring(0, 8)}</Descriptions.Item>
              <Descriptions.Item label="创建者">{issue.created_by || '-'}</Descriptions.Item>
              <Descriptions.Item label="负责人">
                {issue.assigned_agent_name || issue.assigned_agent_id || '未分配'}
              </Descriptions.Item>
              <Descriptions.Item label="任务进度">
                {issue.task_count ?? 0 > 0
                  ? `${issue.completed_task_count ?? 0}/${issue.task_count}`
                  : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="分解策略">
                {issue.decomposition_strategy || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="创建时间" span={2}>
                {new Date(issue.created_at).toLocaleString('zh-CN')}
              </Descriptions.Item>
              <Descriptions.Item label="更新时间" span={2}>
                {new Date(issue.updated_at).toLocaleString('zh-CN')}
              </Descriptions.Item>
            </Descriptions>

            {/* 描述 */}
            {issue.description && (
              <Card title="描述" size="small" style={{ marginTop: 16 }}>
                <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: 0 }}>
                  {issue.description}
                </pre>
              </Card>
            )}

            {/* 附件 */}
            <Card
              title={<><PaperClipOutlined /> 附件</>}
              size="small"
              style={{ marginTop: 16 }}
              extra={
                <Upload
                  accept=".docx,.pdf,.md,.txt"
                  multiple
                  showUploadList={false}
                  beforeUpload={(_file, fileList) => {
                    // Ant Design multiple 模式下 beforeUpload 会被每个文件调用一次
                    // 我们只在最后一个文件时触发批量上传
                    if (_file === fileList[fileList.length - 1]) {
                      handleBatchUpload(fileList);
                    }
                    return false;
                  }}
                >
                  <Button icon={<UploadOutlined />} size="small" loading={uploading}>
                    上传附件
                  </Button>
                </Upload>
              }
            >
              {attachments.length === 0 ? (
                <Typography.Text type="secondary">暂无附件，支持 DOCX、PDF、MD、TXT（单个文件 ≤ 10MB）</Typography.Text>
              ) : (
                <List
                  size="small"
                  dataSource={attachments}
                  renderItem={(att) => (
                    <List.Item
                      actions={[
                        <Button
                          key="download"
                          type="link"
                          size="small"
                          icon={<DownloadOutlined />}
                          onClick={() => {
                            const url = issuesApi.getAttachmentDownloadUrl(issueId!, att.id);
                            window.open(url);
                          }}
                        >
                          下载
                        </Button>,
                        <Popconfirm
                          key="delete"
                          title={`确认删除 ${att.filename}？`}
                          onConfirm={() => handleDeleteAttachment(att.id)}
                        >
                          <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                            删除
                          </Button>
                        </Popconfirm>,
                      ]}
                    >
                      <List.Item.Meta
                        avatar={<PaperClipOutlined style={{ fontSize: 18 }} />}
                        title={att.filename}
                        description={`${(att.file_size / 1024).toFixed(1)} KB · ${att.file_type.toUpperCase()} · ${new Date(att.created_at).toLocaleString('zh-CN')}`}
                      />
                    </List.Item>
                  )}
                />
              )}
            </Card>

            {/* 操作按钮区 */}
            <Card title="操作" size="small" style={{ marginTop: 16 }}>
              <Space>
                <Button type="primary" icon={<ApartmentOutlined />}
                  onClick={handleDecompose} loading={decomposing}
                  disabled={issue.status === 'closed' || !!issue.task_tree}>
                  分解为子任务
                </Button>
                <Button icon={<SendOutlined />}
                  onClick={handleDispatch} loading={dispatching}
                  disabled={!issue.task_tree || issue.status === 'closed'}>
                  派发任务
                </Button>
                <Button icon={<CaretRightOutlined />}
                  onClick={() => navigate(`/tasks`)}>
                  Kanban 看板
                </Button>
              </Space>
            </Card>
          </Card>

          {/* 评论 */}
          <div style={{ marginTop: 16 }}>
            <CommentList issueId={issueId!} />
          </div>
        </Col>

        {/* 右侧: 任务树 */}
        <Col xs={24} lg={10}>
          <Card
            title={<><CaretRightOutlined /> 任务树</>}
            size="small"
            extra={
              taskTree.length > 0 && (
                <Tag>{taskTree.length} 个根节点</Tag>
              )
            }
          >
            <TaskTreeView nodes={taskTree} />
          </Card>
        </Col>
      </Row>

      {/* 编辑 Modal */}
      <Modal title="编辑 Issue" open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={() => form.submit()} okText="保存">
        <Form form={form} layout="vertical" onFinish={handleEdit}>
          <Form.Item name="title" label="标题">
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={4} />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <Select>
              <Select.Option value="critical">严重</Select.Option>
              <Select.Option value="high">高</Select.Option>
              <Select.Option value="medium">中</Select.Option>
              <Select.Option value="low">低</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select>
              {Object.entries(statusMap).map(([k, v]) => (
                <Select.Option key={k} value={k}>{v.label}</Select.Option>
              ))}
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
