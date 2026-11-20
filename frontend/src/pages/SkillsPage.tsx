// ============================================================
// SkillsPage — Skill 市场（真实 API）
// ============================================================

import React, { useState, useMemo, useEffect } from 'react';
import {
  Typography, Card, Row, Col, Button, Tag, Space, Input,
  Select, Drawer, Statistic, App, Tooltip, Spin,
} from 'antd';
import {
  DownloadOutlined, CheckCircleOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { installSkill, uninstallSkill } from '../api/skills';
import { fetchSkills } from '../api/skills';
import type { Skill } from '../types/skill';
import {
  SKILL_CATEGORIES, SKILL_CATEGORY_COLORS,
} from '../constants/skills';

const { Title, Text, Paragraph } = Typography;
const { Search } = Input;

const SkillsPage: React.FC = () => {
  const { message } = App.useApp();
  const [searchText, setSearchText] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // API
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchSkills()
      .then(setSkills)
      .catch((e) => message.error(`加载 Skill 失败: ${e?.message || '未知错误'}`))
      .finally(() => setLoading(false));
  }, []);

  const filteredSkills = useMemo(() => {
    return skills.filter((s) => {
      const matchSearch = !searchText
        || s.name.toLowerCase().includes(searchText.toLowerCase())
        || s.description.includes(searchText)
        || s.tags.some((t) => t.includes(searchText));
      const matchCat = categoryFilter === 'all' || s.category === categoryFilter;
      return matchSearch && matchCat;
    });
  }, [skills, searchText, categoryFilter]);

  const installedCount = skills.filter((s) => s.installed).length;

  const handleInstall = async (skill: Skill) => {
    try {
      await installSkill(skill.id);
      message.success(`成功安装 ${skill.name}`);
      // 刷新列表
      setLoading(true);
      fetchSkills()
        .then(setSkills)
        .catch(() => message.error('刷新列表失败'))
        .finally(() => setLoading(false));
    } catch (e: any) {
      message.error(`安装失败: ${e?.message || '未知错误'}`);
    }
  };

  const handleUninstall = async (skill: Skill) => {
    try {
      await uninstallSkill(skill.id);
      message.success(`已卸载 ${skill.name}`);
      setLoading(true);
      fetchSkills()
        .then(setSkills)
        .catch(() => message.error('刷新列表失败'))
        .finally(() => setLoading(false));
    } catch (e: any) {
      message.error(`卸载失败: ${e?.message || '未知错误'}`);
    }
  };

  const openDetail = (skill: Skill) => {
    setSelectedSkill(skill);
    setDrawerOpen(true);
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>Skill 市场</Title>
          <Text type="secondary">浏览、安装和管理 AI Agent 的可插拔能力插件</Text>
        </div>
        <Space>
          <Tag color="blue">已安装 {installedCount}</Tag>
          <Tag>共 {skills.length} 个</Tag>
        </Space>
      </div>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Search placeholder="搜索 Skill..." allowClear style={{ width: 280 }}
            prefix={<SearchOutlined />}
            onSearch={setSearchText} onChange={(e) => setSearchText(e.target.value)} />
          <Select value={categoryFilter} onChange={setCategoryFilter} style={{ width: 150 }}
            options={[{ value: 'all', label: '全部分类' },
              ...Object.entries(SKILL_CATEGORIES).map(([k, v]) => ({ value: k, label: v })),
            ]} />
        </Space>
      </Card>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
      ) : (
        <Row gutter={[16, 16]}>
          {filteredSkills.map((skill) => (
            <Col xs={24} sm={12} lg={8} xl={6} key={skill.id}>
              <Card hoverable size="small" style={{ height: '100%', position: 'relative' }}
                onClick={() => openDetail(skill)}>
                {skill.installed && (
                  <CheckCircleOutlined style={{
                    position: 'absolute', top: 8, right: 8,
                    fontSize: 18, color: '#52c41a',
                  }} />
                )}

                <Tag color={SKILL_CATEGORY_COLORS[skill.category as keyof typeof SKILL_CATEGORY_COLORS] || '#1677ff'}
                  style={{ marginBottom: 8 }}>
                  {SKILL_CATEGORIES[skill.category as keyof typeof SKILL_CATEGORIES] || skill.category}
                </Tag>

                <Text strong style={{ display: 'block', fontSize: 15, marginBottom: 8 }}>{skill.name}</Text>

                <Paragraph type="secondary" ellipsis={{ rows: 2 }}
                  style={{ marginBottom: 12, minHeight: 42, fontSize: 13 }}>
                  {skill.description}
                </Paragraph>

                <Space wrap size={[4, 4]} style={{ marginBottom: 12 }}>
                  {skill.tags.slice(0, 3).map((t) => <Tag key={t} style={{ fontSize: 12 }}>{t}</Tag>)}
                </Space>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {skill.version || 'v1.0'} · {skill.author || 'Unknown'}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {skill.updated_at ? new Date(skill.updated_at).toLocaleDateString() : '-'}
                  </Text>
                </div>

                <div style={{ marginTop: 12 }}>
                  {skill.installed ? (
                    <Button size="small" block disabled>已安装</Button>
                  ) : (
                    <Button size="small" type="primary" block
                      icon={<DownloadOutlined />}
                      onClick={(e) => { e.stopPropagation(); handleInstall(skill); }}>
                      安装
                    </Button>
                  )}
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      {!loading && filteredSkills.length === 0 && (
        <Card><div style={{ textAlign: 'center', padding: 40, color: '#8c8c8c' }}>没有匹配的 Skill</div></Card>
      )}

      <Drawer title={selectedSkill?.name} open={drawerOpen}
        onClose={() => setDrawerOpen(false)} size="default" destroyOnHidden>
        {selectedSkill && (
          <>
            <div style={{ marginBottom: 16 }}>
              <Tag color={SKILL_CATEGORY_COLORS[selectedSkill.category as keyof typeof SKILL_CATEGORY_COLORS] || '#1677ff'}>
                {SKILL_CATEGORIES[selectedSkill.category as keyof typeof SKILL_CATEGORIES] || selectedSkill.category}
              </Tag>
              {selectedSkill.installed && <Tag color="success">已安装</Tag>}
            </div>

            <Paragraph>{selectedSkill.description}</Paragraph>

            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={8}>
                <Statistic title="版本" value={selectedSkill.version || 'v1.0'} styles={{ content: { fontSize: 16 } }} />
              </Col>
              <Col span={8}>
                <Statistic title="作者" value={selectedSkill.author || '-'} styles={{ content: { fontSize: 16 } }} />
              </Col>
              <Col span={8}>
                <Statistic title="标签" value={selectedSkill.tags.length} suffix="个" styles={{ content: { fontSize: 16 } }} />
              </Col>
            </Row>

            <div style={{ marginBottom: 16 }}>
              <Text type="secondary">创建：</Text>
              <Text>{selectedSkill.created_at ? new Date(selectedSkill.created_at).toLocaleString() : '-'}</Text>
            </div>
            <div style={{ marginBottom: 16 }}>
              <Text type="secondary">更新：</Text>
              <Text>{selectedSkill.updated_at ? new Date(selectedSkill.updated_at).toLocaleString() : '-'}</Text>
            </div>

            <div style={{ marginBottom: 16 }}>
              <Text type="secondary">标签：</Text>
              <Space wrap style={{ marginTop: 4 }}>
                {selectedSkill.tags.map((t) => <Tag key={t}>{t}</Tag>)}
              </Space>
            </div>

            <div style={{ marginTop: 24 }}>
              {selectedSkill?.installed ? (
                <Button block danger onClick={() => handleUninstall(selectedSkill)}>卸载</Button>
              ) : (
                <Button type="primary" block icon={<DownloadOutlined />}
                  onClick={() => handleInstall(selectedSkill)}>安装 Skill</Button>
              )}
            </div>
          </>
        )}
      </Drawer>
    </div>
  );
};

export default SkillsPage;
