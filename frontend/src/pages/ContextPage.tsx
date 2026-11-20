// ============================================================
// ContextPage — 上下文引擎管理页面
// ============================================================

import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, Input, Button, Tabs, Table, Tag, Space, message, Statistic, Row, Col,
  Typography, Spin, Empty, Descriptions, Badge, Tooltip, Modal, App,
} from 'antd';
import {
  SearchOutlined, InboxOutlined, ClearOutlined, SettingOutlined,
  ThunderboltOutlined, FileTextOutlined, ReloadOutlined,
  DatabaseOutlined, CodeOutlined, DeleteOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

import {
  fetchStats, semanticSearch, buildContext, injectContext, indexText,
  cacheStats, clearCache, clearIndex, listIndexEntries, deleteIndexEntry,
} from '../api/context';
import type {
  ContextStats, SearchResult, BuildResponse, IndexEntry,
} from '../api/context';

const { TextArea } = Input;
const { Title, Text, Paragraph } = Typography;

// ============================================================
// 子组件
// ============================================================

/** 引擎统计卡片 */
function StatsCards({ stats }: { stats: ContextStats | null }) {
  if (!stats) return null;
  return (
    <Row gutter={16} style={{ marginBottom: 16 }}>
      <Col span={6}>
        <Card size="small">
          <Statistic
            title="向量索引"
            value={stats.vector_store_count}
            prefix={<DatabaseOutlined />}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small">
          <Statistic
            title="缓存条目"
            value={stats.cache.total_entries}
            prefix={<ThunderboltOutlined />}
            suffix={`/ ${stats.cache.max_entries}`}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small">
          <Statistic
            title="缓存命中"
            value={stats.cache.total_hits}
            prefix={<CodeOutlined />}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small">
          <Statistic
            title="Embedding 维度"
            value={stats.embedding_dim}
            prefix={<SettingOutlined />}
          />
        </Card>
      </Col>
    </Row>
  );
}

/** 搜索 Tab */
function SearchTab() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [contextResult, setContextResult] = useState<BuildResponse | null>(null);

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const res = await semanticSearch(query);
      setResults(res.results);
      message.success(`找到 ${res.count} 条结果`);
    } catch (e) {
      message.error('搜索失败');
    }
    setLoading(false);
  }, [query]);

  const handleBuildContext = useCallback(async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const res = await buildContext(query);
      setContextResult(res);
      message.success(`上下文构建完成 (${res.token_count} tokens, ${res.cache_hit ? '缓存命中' : '检索命中'})`);
    } catch (e) {
      message.error('构建失败');
    }
    setLoading(false);
  }, [query]);

  return (
    <div>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="输入语义搜索查询..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onPressEnter={handleSearch}
            prefix={<SearchOutlined />}
          />
          <Button type="primary" onClick={handleSearch} loading={loading}>搜索</Button>
          <Button onClick={handleBuildContext} loading={loading}>构建上下文</Button>
        </Space.Compact>
      </Card>

      {results.length > 0 && (
        <Card size="small" title={`搜索结果 (${results.length})`} style={{ marginBottom: 16 }}>
          {results.map((r, i) => (
            <Card
              key={r.id}
              size="small"
              type="inner"
              style={{ marginBottom: 8 }}
              title={
                <Space>
                  <Tag color="blue">#{i + 1}</Tag>
                  <Text strong style={{ fontSize: 12 }}>Score: {r.score.toFixed(4)}</Text>
                  {(r.metadata?.title as string) && <Text type="secondary">{String(r.metadata?.title)}</Text>}
                </Space>
              }
            >
              <Paragraph ellipsis={{ rows: 3, expandable: true }}>
                {r.text}
              </Paragraph>
            </Card>
          ))}
        </Card>
      )}

      {contextResult && (
        <Card size="small" title={
          <Space>
            <span>构建结果</span>
            <Tag color={contextResult.cache_hit ? 'green' : 'blue'}>
              {contextResult.cache_hit ? '缓存命中' : '检索命中'}
            </Tag>
            <Tag>{contextResult.token_count} tokens</Tag>
          </Space>
        }>
          <Paragraph
            style={{
              maxHeight: 400,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              background: '#fafafa',
              padding: 12,
              borderRadius: 4,
              fontSize: 13,
            }}
          >
            {contextResult.context}
          </Paragraph>
        </Card>
      )}

      {!loading && !results.length && !contextResult && (
        <Empty description="输入查询开始语义搜索" />
      )}
    </div>
  );
}

/** 索引 Tab */
function IndexTab({ refreshStats }: { refreshStats: () => void }) {
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);
  const [entries, setEntries] = useState<IndexEntry[]>([]);
  const [entriesLoading, setEntriesLoading] = useState(false);

  const loadEntries = useCallback(async () => {
    setEntriesLoading(true);
    try {
      const res = await listIndexEntries();
      setEntries(res.entries);
    } catch { /* ignore */ }
    setEntriesLoading(false);
  }, []);

  useEffect(() => { loadEntries(); }, [loadEntries]);

  const handleIndex = useCallback(async () => {
    if (!text.trim()) return;
    setLoading(true);
    try {
      const res = await indexText(text);
      message.success(`索引成功: ${res.indexed_chunks} 个块`);
      setText('');
      loadEntries();
      refreshStats();
    } catch {
      message.error('索引失败');
    }
    setLoading(false);
  }, [text, loadEntries, refreshStats]);

  const handleClear = useCallback(async () => {
    Modal.confirm({
      title: '确认清空',
      content: '确定要清空所有向量索引吗？此操作不可撤销。',
      onOk: async () => {
        await clearIndex();
        message.success('索引已清空');
        loadEntries();
        refreshStats();
      },
    });
  }, [loadEntries, refreshStats]);

  const columns: ColumnsType<IndexEntry> = [
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
    {
      title: '类型', dataIndex: 'source_type', key: 'source_type', width: 100,
      render: (t: string) => <Tag>{t}</Tag>,
    },
    { title: '块数', dataIndex: 'chunk_count', key: 'chunk_count', width: 80 },
    { title: 'Tokens', dataIndex: 'token_count', key: 'token_count', width: 80 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => <Badge status={s === 'active' ? 'success' : 'default'} text={s} />,
    },
    {
      title: '时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (t: string) => t ? new Date(t).toLocaleString() : '-',
    },
    {
      title: '操作', key: 'action', width: 80,
      render: (_: unknown, record: IndexEntry) => (
        <Tooltip title="删除">
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={async () => {
              await deleteIndexEntry(record.id);
              message.success('已删除');
              loadEntries();
            }}
          />
        </Tooltip>
      ),
    },
  ];

  return (
    <div>
      <Card size="small" style={{ marginBottom: 16 }}>
        <TextArea
          rows={4}
          placeholder="输入要索引的文本内容（自动分块 + 向量化）..."
          value={text}
          onChange={(e) => setText(e.target.value)}
          style={{ marginBottom: 12 }}
        />
        <Space>
          <Button type="primary" icon={<InboxOutlined />} onClick={handleIndex} loading={loading}>
            索引文本
          </Button>
          <Button icon={<ClearOutlined />} onClick={handleClear} danger>
            清空索引
          </Button>
        </Space>
      </Card>

      <Card
        size="small"
        title={`索引条目 (${entries.length})`}
        extra={<Button icon={<ReloadOutlined />} onClick={loadEntries} size="small" />}
      >
        <Table
          columns={columns}
          dataSource={entries}
          rowKey="id"
          loading={entriesLoading}
          size="small"
          pagination={{ pageSize: 10 }}
        />
      </Card>
    </div>
  );
}

/** 缓存 Tab */
function CacheTab() {
  const [cache, setCache] = useState<ContextStats['cache'] | null>(null);

  const loadCache = useCallback(async () => {
    try {
      const res = await cacheStats();
      setCache(res);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadCache(); }, [loadCache]);

  const handleClear = useCallback(async () => {
    Modal.confirm({
      title: '确认清空',
      content: '确定要清空所有语义缓存吗？',
      onOk: async () => {
        await clearCache();
        message.success('缓存已清空');
        loadCache();
      },
    });
  }, [loadCache]);

  return (
    <div>
      {cache && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Descriptions column={2} size="small">
            <Descriptions.Item label="缓存条目">{cache.total_entries}</Descriptions.Item>
            <Descriptions.Item label="最大容量">{cache.max_entries}</Descriptions.Item>
            <Descriptions.Item label="累计命中">{cache.total_hits}</Descriptions.Item>
            <Descriptions.Item label="默认 TTL">{cache.default_ttl_sec}s</Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      <Card size="small" title="缓存管理">
        <Space>
          <Button icon={<ClearOutlined />} onClick={handleClear} danger>清空缓存</Button>
          <Button icon={<ReloadOutlined />} onClick={loadCache}>刷新</Button>
        </Space>
      </Card>
    </div>
  );
}

// ============================================================
// 主页面
// ============================================================

const ContextPage: React.FC = () => {
  const { message } = App.useApp();
  const [stats, setStats] = useState<ContextStats | null>(null);

  const loadStats = useCallback(async () => {
    try {
      const s = await fetchStats();
      setStats(s);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadStats(); }, [loadStats]);

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>
        <DatabaseOutlined /> Context Engine
        <Text type="secondary" style={{ fontSize: 14, marginLeft: 8 }}>
          上下文引擎 — 语义搜索 · 向量索引 · 自动注入
        </Text>
      </Title>

      <StatsCards stats={stats} />

      <Tabs
        defaultActiveKey="search"
        items={[
          {
            key: 'search',
            label: <span><SearchOutlined /> 语义搜索</span>,
            children: <SearchTab />,
          },
          {
            key: 'index',
            label: <span><InboxOutlined /> 索引管理</span>,
            children: <IndexTab refreshStats={loadStats} />,
          },
          {
            key: 'cache',
            label: <span><ThunderboltOutlined /> 语义缓存</span>,
            children: <CacheTab />,
          },
        ]}
      />
    </div>
  );
};

export default ContextPage;
