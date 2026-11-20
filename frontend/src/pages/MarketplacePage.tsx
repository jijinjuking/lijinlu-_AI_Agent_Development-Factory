/**
 * MarketplacePage - AI 能力市场页面
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Table, Button, Tag, Card, Space, message, Typography, Tooltip, Input, Select, Rate, Badge, Modal, Form } from 'antd';
import { ReloadOutlined, PlusOutlined, DownloadOutlined, SearchOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { fetchPackages, installPackage, checkUpdates, publishPackage, searchPackages, type MarketplacePackage, type PackageType } from '../api/marketplace';

const { Text, Paragraph } = Typography;

const typeColors: Record<PackageType, string> = { skill: 'blue', agent: 'green', workflow: 'purple' };
const statusColors: Record<string, 'default' | 'processing' | 'success' | 'warning'> = { draft: 'default', pending_review: 'processing', published: 'success', deprecated: 'warning', archived: 'default' };

export default function MarketplacePage() {
  const [packages, setPackages] = useState<MarketplacePackage[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [typeFilter, setTypeFilter] = useState<PackageType | undefined>(undefined);
  
  // 发布模态框状态
  const [publishModalVisible, setPublishModalVisible] = useState(false);
  const [publishLoading, setPublishLoading] = useState(false);
  const [publishForm] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      let data: MarketplacePackage[];
      if (searchText) {
        data = await searchPackages(searchText);
      } else {
        data = await fetchPackages({ package_type: typeFilter });
      }
      setPackages(data);
    } catch (e: unknown) { message.error(`加载失败: ${(e as Error).message}`); } finally { setLoading(false); }
  }, [searchText, typeFilter]);

  useEffect(() => { load(); }, [load]);

  const handleInstall = async (pkg: MarketplacePackage) => {
    try { await installPackage(pkg.package_id); message.success(`"${pkg.name}" 安装成功`); load(); } catch (e: unknown) { message.error(`安装失败: ${(e as Error).message}`); }
  };

  const handlePublish = async (values: any) => {
    setPublishLoading(true);
    try {
      const tags = values.tags ? values.tags.split(',').map((t: string) => t.trim()).filter(Boolean) : [];
      await publishPackage({
        name: values.name,
        description: values.description,
        package_type: values.package_type,
        version: values.version,
        tags: tags,
      });
      message.success('能力包发布成功！');
      setPublishModalVisible(false);
      publishForm.resetFields();
      load();
    } catch (e: unknown) {
      message.error(`发布失败: ${(e as Error).message}`);
    } finally {
      setPublishLoading(false);
    }
  };

  const columns: ColumnsType<MarketplacePackage> = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 160, ellipsis: true, render: (n: string, r: MarketplacePackage) => <Tooltip title={r.description || n}><a onClick={() => handleInstall(r)}>{n}</a></Tooltip> },
    { title: '类型', dataIndex: 'package_type', key: 'package_type', width: 80, render: (t: PackageType) => <Tag color={typeColors[t]}>{t}</Tag> },
    { title: '版本', dataIndex: 'version', key: 'version', width: 80 },
    { title: '作者', dataIndex: 'author', key: 'author', width: 100, ellipsis: true },
    {
      title: '评分', key: 'rating', width: 140,
      render: (_: unknown, r: MarketplacePackage) => <Rate disabled value={r.rating} allowHalf style={{ fontSize: 12 }} />,
    },
    { title: '下载量', dataIndex: 'download_count', key: 'download_count', width: 80, align: 'center' as const },
    { title: '标签', dataIndex: 'tags', key: 'tags', width: 160, render: (tags: string[]) => tags?.map((t) => <Tag key={t}>{t}</Tag>) },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (s: string) => <Badge status={statusColors[s] ?? 'default'} text={s} /> },
    {
      title: '操作', key: 'actions', width: 100,
      render: (_: unknown, r: MarketplacePackage) => (
        <Tooltip title="安装"><Button size="small" type="primary" icon={<DownloadOutlined />} onClick={() => handleInstall(r)} /></Tooltip>
      ),
    },
  ];

  return (
    <div>
      <Card
        title="AI 能力市场"
        extra={
          <Space>
            <Input.Search 
              placeholder="搜索能力包..." 
              allowClear 
              style={{ width: 200 }} 
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onSearch={(value) => {
                setSearchText(value);
                load();
              }}
              enterButton={<SearchOutlined />}
            />
            <Select 
              placeholder="类型" 
              allowClear 
              style={{ width: 120 }} 
              value={typeFilter} 
              onChange={(value) => {
                setTypeFilter(value);
              }} 
              options={[{ label: 'Skill', value: 'skill' }, { label: 'Agent', value: 'agent' }, { label: 'Workflow', value: 'workflow' }]} 
            />
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setPublishModalVisible(true)}>发布能力</Button>
          </Space>
        }
      >
        <Table rowKey="package_id" columns={columns} dataSource={packages} loading={loading} pagination={{ pageSize: 20 }} size="small" scroll={{ x: 1000 }} />
        <Paragraph type="secondary" style={{ marginTop: 8 }}>AI Marketplace — Skill / Agent / Workflow 能力包发布、搜索、安装、评分</Paragraph>
      </Card>

      <Modal
        title="发布能力包"
        open={publishModalVisible}
        onCancel={() => {
          setPublishModalVisible(false);
          publishForm.resetFields();
        }}
        footer={null}
        width={600}
      >
        <Form
          form={publishForm}
          layout="vertical"
          onFinish={handlePublish}
          style={{ marginTop: 20 }}
        >
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入能力包名称' }]}
          >
            <Input placeholder="请输入能力包名称" />
          </Form.Item>

          <Form.Item
            name="package_type"
            label="类型"
            rules={[{ required: true, message: '请选择类型' }]}
          >
            <Select
              placeholder="请选择类型"
              options={[
                { label: 'Skill', value: 'skill' },
                { label: 'Agent', value: 'agent' },
                { label: 'Workflow', value: 'workflow' },
              ]}
            />
          </Form.Item>

          <Form.Item
            name="version"
            label="版本"
            rules={[{ required: true, message: '请输入版本号' }]}
          >
            <Input placeholder="例如: 1.0.0" />
          </Form.Item>

          <Form.Item
            name="description"
            label="描述"
            rules={[{ required: true, message: '请输入描述' }]}
          >
            <Input.TextArea rows={4} placeholder="请输入能力包描述" />
          </Form.Item>

          <Form.Item
            name="category"
            label="分类"
          >
            <Input placeholder="请输入分类（可选）" />
          </Form.Item>

          <Form.Item
            name="tags"
            label="标签"
            help="多个标签用逗号分隔"
          >
            <Input placeholder="例如: AI, 自动化, 工具（可选）" />
          </Form.Item>

          <Form.Item
            name="price"
            label="价格"
            help="留空表示免费"
          >
            <Input type="number" placeholder="请输入价格（可选）" />
          </Form.Item>

          <Form.Item style={{ textAlign: 'right', marginBottom: 0 }}>
            <Space>
              <Button onClick={() => {
                setPublishModalVisible(false);
                publishForm.resetFields();
              }}>
                取消
              </Button>
              <Button type="primary" htmlType="submit" loading={publishLoading}>
                发布
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}