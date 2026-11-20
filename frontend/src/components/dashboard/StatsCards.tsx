// ============================================================
// StatsCards — Dashboard 统计卡片组（真实 API + 可点击跳转）
// ============================================================

import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Row, Col, Typography } from 'antd';
import StatsCard from '../common/StatsCard';
import { fetchStats } from '../../api/dashboard';
import type { StatCardData } from '../../types/common';

const { Title } = Typography;

/** stat.key → 目标路由映射 */
const ROUTE_MAP: Record<string, string> = {
  agents: '/agents',
  pipelines: '/pipelines',
  tasks: '/agents',       // 完成任务来自 Agent 统计
  tokens: '/costs',
  cost: '/costs',
  success_rate: '/pipelines',
};

interface StatsCardsProps {
  title?: string;
}

const StatsCards: React.FC<StatsCardsProps> = ({ title = '运行概况' }) => {
  const [stats, setStats] = useState<StatCardData[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    fetchStats()
      .then((data) => { setStats(data); setLoading(false); })
      .catch(() => { setLoading(false); });
  }, []);

  return (
    <div>
      <Title level={4} style={{ margin: '0 0 16px 0' }}>
        {title}
      </Title>
      <Row gutter={[16, 16]}>
        {stats.map((stat) => {
          const route = ROUTE_MAP[stat.key];
          return (
            <Col xs={24} sm={12} md={8} lg={8} xl={4} key={stat.key}>
              <StatsCard
                title={stat.title}
                value={stat.value}
                suffix={stat.suffix}
                trend={stat.trend}
                trendLabel={stat.trendLabel}
                color={stat.color}
                loading={loading}
                onClick={route ? () => navigate(route) : undefined}
              />
            </Col>
          );
        })}
      </Row>
    </div>
  );
};

export default StatsCards;
