// ============================================================
// StatsCard — 统计卡片组件（Dashboard 用，支持点击跳转）
// ============================================================

import React from 'react';
import { Card, Typography } from 'antd';
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons';

const { Text } = Typography;

interface StatsCardProps {
  title: string;
  value: number | string;
  prefix?: string;
  suffix?: string;
  trend?: number;
  trendLabel?: string;
  color?: string;
  loading?: boolean;
  onClick?: () => void;
}

const StatsCard: React.FC<StatsCardProps> = ({
  title,
  value,
  prefix,
  suffix,
  trend,
  trendLabel,
  color,
  loading = false,
  onClick,
}) => {
  const isUp = trend !== undefined && trend >= 0;
  const trendColor = isUp ? '#52c41a' : '#ff4d4f';
  const clickable = !!onClick;

  return (
    <Card
      loading={loading}
      size="small"
      hoverable={clickable}
      onClick={onClick}
      style={{
        height: '100%',
        borderTop: `3px solid ${color || '#1677ff'}`,
        cursor: clickable ? 'pointer' : 'default',
        transition: 'box-shadow 0.2s',
      }}
      styles={{ body: { padding: '16px 20px' } }}
    >
      <Text type="secondary" style={{ fontSize: 13 }}>
        {title}
      </Text>

      <div style={{ margin: '8px 0' }}>
        <Text strong style={{ fontSize: 28, color: color || '#1677ff' }}>
          {prefix}{value}{suffix}
        </Text>
      </div>

      {trend !== undefined && (
        <div style={{ fontSize: 12 }}>
          <span style={{ color: trend === 0 ? '#8c8c8c' : trendColor }}>
            {trend === 0 ? (
              <span>— 0%</span>
            ) : (
              <>
                {isUp ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
                {' '}{Math.abs(trend)}%
              </>
            )}
          </span>
          {trendLabel && (
            <Text type="secondary" style={{ marginLeft: 6 }}>
              {trendLabel}
            </Text>
          )}
        </div>
      )}
    </Card>
  );
};

export default StatsCard;
