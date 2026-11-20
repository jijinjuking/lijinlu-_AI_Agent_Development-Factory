/**
 * PerformancePage - 性能监控页面
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Card, Space, Select, Typography, Table, Tag, Progress, Tooltip, Button, Statistic, Row, Col, Alert, Badge } from 'antd';
import { ReloadOutlined, WarningOutlined } from '@ant-design/icons';
import { fetchPerformanceSummary, fetchSlowQueries, fetchSystemHealth, type PerformanceSummary, type SlowQuery } from '../api/performance';

const { Text, Title, Paragraph } = Typography;

const periodOptions = [
  { label: '近 1 小时', value: '1h' },
  { label: '近 24 小时', value: '24h' },
  { label: '近 7 天', value: '7d' },
  { label: '近 30 天', value: '30d' },
];

export default function PerformancePage() {
  const [period, setPeriod] = useState<string>('24h');
  const [summary, setSummary] = useState<PerformanceSummary | null>(null);
  const [slowQueries, setSlowQueries] = useState<SlowQuery[]>([]);
  const [health, setHealth] = useState<{ status: string; checks: { name: string; status: string; detail?: string }[] } | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, sq, h] = await Promise.all([
        fetchPerformanceSummary(period as '1h' | '24h' | '7d' | '30d'),
        fetchSlowQueries(10),
        fetchSystemHealth(),
      ]);
      setSummary(s);
      setSlowQueries(sq);
      setHealth(h);
    } catch (e: unknown) {
      // 后端可能还没有这些接口，静默处理
    } finally { setLoading(false); }
  }, [period]);

  useEffect(() => { load(); }, [load]);

  const healthColor: Record<string, 'success' | 'warning' | 'error'> = { healthy: 'success', degraded: 'warning', unhealthy: 'error' };

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>性能监控</Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>系统性能指标、慢查询分析、健康度检查</Text>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card><Statistic title="Avg CPU %" value={summary?.avg_cpu_percent ?? '-'} precision={1} suffix="%" /></Card></Col>
        <Col span={6}><Card><Statistic title="Avg 内存" value={summary ? (summary.avg_memory_mb / 1024).toFixed(1) : '-'} suffix="GB" /></Card></Col>
        <Col span={6}><Card><Statistic title="P95 响应" value={summary?.p95_response_ms ?? '-'} suffix="ms" styles={{ content: { color: (summary && summary.p95_response_ms > 1000) ? '#ff4d4f' : undefined } }} /></Card></Col>
        <Col span={6}><Card><Statistic title="错误率" value={summary?.error_rate_percent ?? '-'} precision={2} suffix="%" styles={{ content: { color: (summary && summary.error_rate_percent > 1) ? '#ff4d4f' : '#52c41a' } }} /></Card></Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}><Card><Statistic title="Avg 响应时间" value={summary?.avg_response_ms ?? '-'} suffix="ms" /></Card></Col>
        <Col span={8}><Card><Statistic title="QPS" value={summary?.requests_per_second ?? '-'} /></Card></Col>
        <Col span={8}><Card><Space><Select value={period} onChange={setPeriod} options={periodOptions} style={{ width: 140 }} /><Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button></Space></Card></Col>
      </Row>

      {health && health.status !== 'healthy' && (
        <Alert type="warning" showIcon icon={<WarningOutlined />} message={`系统健康状态: ${health.status}`} style={{ marginBottom: 16 }} />
      )}

      {health && (
        <Card title="健康检测" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            {health.checks.map((c) => (
              <Col span={8} key={c.name}>
                <Space><Badge status={c.status === 'pass' ? 'success' : c.status === 'fail' ? 'error' : 'warning'} /> <Text>{c.name}: {c.status}</Text></Space>
                {c.detail && <Text type="secondary" style={{ fontSize: 11 }}> {c.detail}</Text>}
              </Col>
            ))}
          </Row>
        </Card>
      )}

      <Card title="慢查询 Top 10" style={{ marginBottom: 16 }}>
        <Table
          rowKey="query_id"
          columns={[
            { title: '查询', dataIndex: 'query', key: 'query', ellipsis: true },
            { title: '平均耗时 (ms)', dataIndex: 'avg_duration_ms', key: 'avg_duration_ms', width: 140, sorter: (a: SlowQuery, b: SlowQuery) => a.avg_duration_ms - b.avg_duration_ms, render: (v: number) => <Tag color={v > 1000 ? 'red' : v > 500 ? 'orange' : 'green'}>{v}ms</Tag> },
            { title: '调用次数', dataIndex: 'call_count', key: 'call_count', width: 100 },
            { title: '最后出现', dataIndex: 'last_seen', key: 'last_seen', width: 180 },
          ]}
          dataSource={slowQueries}
          pagination={false}
          size="small"
        />
        {slowQueries.length === 0 && <Paragraph type="secondary">暂无慢查询数据（后端接口可能尚未实现）</Paragraph>}
      </Card>

      <Paragraph type="secondary">Performance Monitoring — 系统指标采集、慢查询分析、健康度评分、自动告警</Paragraph>
    </div>
  );
}
