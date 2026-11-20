// ============================================================
// AppLayout — 主布局容器（需要认证）
// ============================================================

import React, { useEffect } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { Layout, ConfigProvider, App as AntApp } from 'antd';
import { useAppStore } from '../../stores/appStore';
import { useAuth } from '../../contexts/AuthContext';
import { darkTheme, lightTheme } from '../../styles/theme';
import Sidebar from './Sidebar';
import Header from './Header';

const { Content } = Layout;

const AppLayout: React.FC = () => {
  const { theme, sidebarCollapsed, toggleTheme, toggleSidebar } = useAppStore();
  const { isAuthenticated, isLoading } = useAuth();
  const navigate = useNavigate();
  const isDark = theme === 'dark';

  // 认证守卫：未登录 → /login
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      navigate('/login', { replace: true });
    }
  }, [isLoading, isAuthenticated, navigate]);

  // 正在校验 token，暂不渲染
  if (isLoading) {
    return null;
  }

  // 未认证时不渲染布局（守卫 effect 会跳转）
  if (!isAuthenticated) {
    return null;
  }

  return (
    <ConfigProvider theme={isDark ? darkTheme : lightTheme}>
      <AntApp>
        <Layout style={{ height: '100vh', overflow: 'hidden' }}>
          {/* 左侧导航 */}
          <Sidebar collapsed={sidebarCollapsed} theme={theme} />

          {/* 右侧内容区 */}
          <Layout>
            {/* 顶部 Header */}
            <Header
              collapsed={sidebarCollapsed}
              theme={theme}
              onToggleCollapsed={toggleSidebar}
              onToggleTheme={toggleTheme}
            />

            {/* 内容区 */}
            <Content
              style={{
                padding: 24,
                overflow: 'auto',
                background: isDark ? '#0d1117' : '#f5f5f5',
              }}
            >
              <Outlet />
            </Content>
          </Layout>
        </Layout>
      </AntApp>
    </ConfigProvider>
  );
};

export default AppLayout;
