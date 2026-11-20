// ============================================================
// DashboardPage — 仪表盘首页
// ============================================================

import React from 'react';
import StatsCards from '../components/dashboard/StatsCards';
import RecentActivityPanel from '../components/dashboard/RecentActivity';

const DashboardPage: React.FC = () => {
  return (
    <div>
      <StatsCards title="运行概况" />
      <RecentActivityPanel />
    </div>
  );
};

export default DashboardPage;
