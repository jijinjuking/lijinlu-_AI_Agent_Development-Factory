// ============================================================
// CostsPage — 成本分析（真实 API）
// ============================================================

import React, { useState, useMemo, useEffect } from 'react';
import {
  Typography, Card, Row, Col, Table, Statistic, Select,
  Space, Tabs, Tag, Progress, Spin,
} from 'antd';
import {
  DollarOutlined, ThunderboltOutlined, RiseOutlined,
  TrophyOutlined, PieChartOutlined, TableOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  fetchCostSummary, fetchCostRecords,
  fetchCostByModel, fetchCostByAgent, fetchCostTrend,
  type CostSummary, type CostRecord, type CostTrendItem,
} from '../api/costs';
import ReactEChartsCore from 'echarts-for-react';

const { Title, Text } = Typography;

const CostsPage: React.FC = () => {
  const [timeRange, setTimeRange] = useState<string>('7d');
  const [viewTab, setViewTab] = useState<string>('records');

  // API state
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [records, setRecords] = useState<CostRecord[]>([]);
  const [totalRecords, setTotalRecords] = useState(0);
  const [modelCosts, setModelCosts] = useState<any[]>([]);
  const [agentCosts, setAgentCosts] = useState<any[]>([]);
  const [trendData, setTrendData] = useState<CostTrendItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const days = timeRange === '24h' ? 1 : timeRange === '7d' ? 7 : timeRange === '30d' ? 30 : 365;
    Promise.all([
      fetchCostSummary(),
      fetchCostRecords({ page: 1, page_size: 100 }),
      fetchCostByModel(),
      fetchCostByAgent(),
      fetchCostTrend(days),
    ])
      .then(([sum, recs, models, agents, trend]) => {
        setSummary(sum);
        setRecords(recs.list || []);
        setTotalRecords(recs.total || 0);
        setModelCosts(models);
        setAgentCosts(agents);
        setTrendData(trend);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [timeRange]);

  const trendOption = useMemo(() => ({
    tooltip: { trigger: 'axis' as const },
    legend: { data: ['费用 (¥)', 'Token (万)'], bottom: 0, textStyle: { color: '#8c8c8c' } },
    grid: { top: 20, right: 20, bottom: 30, left: 50 },
    xAxis: { type: 'category' as const, data: trendData.map((d) => d.date),
      axisLabel: { color: '#8c8c8c' } },
    yAxis: [
      { type: 'value' as const, name: '¥', axisLabel: { color: '#8c8c8c' },
        splitLine: { lineStyle: { color: '#30363d' } } },
      { type: 'value' as const, name: '万 Token', axisLabel: { color: '#8c8c8c' } },
    ],
    series: [
      { name: '费用 (¥)', type: 'line', data: trendData.map((d) => d.cost),
        smooth: true, symbol: 'circle', symbolSize: 6,
        itemStyle: { color: '#1677ff' }, lineStyle: { width: 2 } },
      { name: 'Token (万)', type: 'line', yAxisIndex: 1,
        data: trendData.map((d) => +(d.tokens / 10000).toFixed(1)),
        smooth: true, symbol: 'diamond', symbolSize: 6,
        itemStyle: { color: '#52c41a' }, lineStyle: { width: 2, type: 'dashed' } },
    ],
  }), [trendData]);

  const topAgent = useMemo(() => {
    if (agentCosts.length === 0) return { name: '-', cost: 0 };
    const top = agentCosts.reduce((a: any, b: any) => (b.cost > a.cost ? b : a), agentCosts[0]);
    return { name: top.agent_name || '-', cost: top.cost || 0 };
  }, [agentCosts]);

  const costColumns: ColumnsType<CostRecord> = [
    { title: '时间', dataIndex: 'created_at', key: 'date', width: 130,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '-' },
    { title: 'Agent', dataIndex: 'agent_name', key: 'agent', width: 130, render: (v: string) => v || '-' },
    { title: '模型', dataIndex: 'model', key: 'model', width: 150,
      render: (v: string) => <Tag>{v || '-'}</Tag> },
    { title: '总 Token', dataIndex: 'tokens', key: 'total', width: 90,
      render: (v: number) => <Text strong>{v?.toLocaleString() ?? 0}</Text> },
    { title: '费用', dataIndex: 'cost', key: 'cost', width: 80,
      render: (v: number) => <Text style={{ color: '#fa8c16' }}>¥{v?.toFixed(2) ?? '0.00'}</Text> },
  ];

  const modelColumns: ColumnsType<any> = [
    { title: '模型', dataIndex: 'model', key: 'model', render: (v: string) => <Text strong>{v}</Text> },
    { title: '调用次数', dataIndex: 'call_count', key: 'calls', render: (v: number) => v ?? '-' },
    { title: '总 Token', dataIndex: 'tokens', key: 'tokens',
      render: (v: number) => (v ?? 0).toLocaleString() },
    { title: '费用', dataIndex: 'cost', key: 'cost',
      render: (v: number) => <Text style={{ color: '#fa8c16' }}>¥{(v ?? 0).toFixed(2)}</Text> },
  ];

  const agentColumns: ColumnsType<any> = [
    { title: 'Agent', dataIndex: 'agent_name', key: 'agent', render: (v: string) => <Text strong>{v}</Text> },
    { title: '总 Token', dataIndex: 'tokens', key: 'tokens',
      render: (v: number) => (v ?? 0).toLocaleString() },
    { title: '总费用', dataIndex: 'cost', key: 'cost',
      render: (v: number) => <Text style={{ color: '#fa8c16' }}>¥{(v ?? 0).toFixed(2)}</Text> },
  ];

  if (loading || !summary) {
    return (
      <div>
        <Title level={4}>成本分析</Title>
        <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>成本分析</Title>
          <Text type="secondary">AI Agent 运行费用明细，Token 消耗趋势，预算管控</Text>
        </div>
        <Select value={timeRange} onChange={setTimeRange} style={{ width: 120 }}
          options={[
            { value: '24h', label: '最近 24 小时' },
            { value: '7d', label: '最近 7 天' },
            { value: '30d', label: '最近 30 天' },
            { value: 'all', label: '全部' },
          ]} />
      </div>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={12} md={6}>
          <Card size="small">
            <Statistic title="今日费用" value={summary.today_cost}
              precision={2} prefix="¥" suffix={<RiseOutlined style={{ color: '#ff4d4f', fontSize: 14 }} />}
              styles={{ content: { color: '#fa8c16' } }} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card size="small">
            <Statistic title="本周费用" value={summary.week_cost}
              precision={2} prefix="¥"
              styles={{ content: { color: '#fa8c16' } }} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card size="small">
            <Statistic title="本月费用" value={summary.month_cost}
              precision={2} prefix="¥"
              styles={{ content: { color: '#fa8c16' } }} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card size="small">
            <Statistic title="今日 Token" value={summary.today_tokens}
              suffix="tokens"
              prefix={<ThunderboltOutlined style={{ color: '#1677ff' }} />} />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={12} md={6}>
          <Card size="small">
            <Statistic title="累计费用" value={summary.total_cost}
              precision={2} prefix="¥" />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card size="small">
            <Statistic title="总 Token" value={`${(summary.total_tokens / 10000).toFixed(1)}万`}
              prefix={<ThunderboltOutlined style={{ color: '#1677ff' }} />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card size="small">
            <Statistic title="费用最高 Agent" value={topAgent.name}
              prefix={<TrophyOutlined style={{ color: '#faad14' }} />} />
            <Text type="secondary" style={{ fontSize: 12 }}>累计 ¥{topAgent.cost.toFixed(2)}</Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card size="small">
            <Statistic title="记录条数" value={totalRecords}
              prefix={<DollarOutlined style={{ color: '#52c41a' }} />}
              suffix="条" />
          </Card>
        </Col>
      </Row>

      <Card title="费用 & Token 趋势" size="small" style={{ marginBottom: 16 }}>
        {trendData.length > 0 ? (
          <ReactEChartsCore option={trendOption} style={{ height: 280 }} />
        ) : (
          <div style={{ textAlign: 'center', padding: 40, color: '#8c8c8c' }}>暂无趋势数据</div>
        )}
      </Card>

      <Card>
        <Tabs activeKey={viewTab} onChange={setViewTab}
          items={[
            { key: 'records', label: <Space><TableOutlined />费用明细</Space>,
              children: <Table columns={costColumns} dataSource={records}
                rowKey="id" size="small" pagination={{ pageSize: 10 }} /> },
            { key: 'byModel', label: <Space><PieChartOutlined />按模型</Space>,
              children: <Table columns={modelColumns} dataSource={modelCosts}
                rowKey="model" size="small" pagination={false} /> },
            { key: 'byAgent', label: <Space><TrophyOutlined />按 Agent</Space>,
              children: <Table columns={agentColumns} dataSource={agentCosts}
                rowKey="agent_name" size="small" pagination={false} /> },
          ]} />
      </Card>
    </div>
  );
};

export default CostsPage;
