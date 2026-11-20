// Header — 顶部工具栏
// ============================================================

import React, { useCallback } from 'react';
import { Layout, Button, Space, Badge, Tooltip, Typography, Dropdown, Avatar } from 'antd';
import type { MenuProps } from 'antd';
import { useNavigate } from 'react-router-dom';
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SunOutlined,
  MoonOutlined,
  BellOutlined,
  SyncOutlined,
  UserOutlined,
  LogoutOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { useAuth } from '../../contexts/AuthContext';

const { Header: AntHeader } = Layout;
const { Text } = Typography;

interface HeaderProps {
  collapsed: boolean;
  theme: 'light' | 'dark';
  onToggleCollapsed: () => void;
  onToggleTheme: () => void;
}

const Header: React.FC<HeaderProps> = ({
  collapsed,
  theme,
  onToggleCollapsed,
  onToggleTheme,
}) => {
  const isDark = theme === 'dark';
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = useCallback(() => {
    logout();
    navigate('/login', { replace: true });
  }, [logout, navigate]);

  const userMenuItems: MenuProps['items'] = [
    {
      key: 'user-info',
      label: (
        <div style={{ padding: '4px 0' }}>
          <div style={{ fontWeight: 600 }}>{user?.display_name || user?.username || '用户'}</div>
          <div style={{ fontSize: 12, color: '#999' }}>{user?.email || ''}</div>
        </div>
      ),
      disabled: true,
    },
    { type: 'divider' },
    {
      key: 'settings',
      icon: <SettingOutlined />,
      label: '个人设置',
      disabled: true, // TODO: 实现设置页
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '登出',
      danger: true,
      onClick: handleLogout,
    },
  ];

  const userMenuProps: MenuProps = {
    items: userMenuItems,
  };

  return (
    <AntHeader
      style={{
        height: 56,
        lineHeight: '56px',
        padding: '0 20px',
        background: isDark ? '#161b22' : '#fff',
        borderBottom: isDark ? '1px solid #30363d' : '1px solid #f0f0f0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}
    >
      {/* 左侧：折叠按钮 + 标题 */}
      <Space>
        <Button
          type="text"
          icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          onClick={onToggleCollapsed}
          style={{ fontSize: 16, color: isDark ? '#e6edf3' : '#000' }}
        />
        <Text
          strong
          style={{
            fontSize: 15,
            color: isDark ? '#e6edf3' : '#000',
          }}
        >
          李金路 AI Agent 开发工厂
        </Text>
      </Space>

      {/* 右侧：操作按钮 */}
      <Space size="middle">
        {/* 同步状态 */}
        <Tooltip title="系统运行正常">
          <Badge status="success" text="" />
        </Tooltip>

        {/* 刷新 */}
        <Tooltip title="刷新数据">
          <Button
            type="text"
            icon={<SyncOutlined />}
            style={{ color: isDark ? '#e6edf3' : '#000' }}
          />
        </Tooltip>

        {/* 通知 */}
        <Tooltip title="通知">
          <Badge count={3} size="small">
            <Button
              type="text"
              icon={<BellOutlined />}
              style={{ color: isDark ? '#e6edf3' : '#000' }}
            />
          </Badge>
        </Tooltip>

        {/* 主题切换 */}
        <Tooltip title={isDark ? '切换亮色主题' : '切换暗色主题'}>
          <Button
            type="text"
            icon={isDark ? <SunOutlined /> : <MoonOutlined />}
            onClick={onToggleTheme}
            style={{ color: isDark ? '#e6edf3' : '#000' }}
          />
        </Tooltip>

        {/* 用户菜单 */}
        <Dropdown menu={userMenuProps} placement="bottomRight">
          <Space style={{ cursor: 'pointer', marginLeft: 8 }}>
            <Avatar
              size="small"
              icon={<UserOutlined />}
              style={{
                backgroundColor: isDark ? '#1f6feb' : '#1677ff',
              }}
            />
            <Typography.Text
              style={{
                color: isDark ? '#e6edf3' : '#000',
                fontSize: 13,
              }}
            >
              {user?.display_name || user?.username || '用户'}
            </Typography.Text>
          </Space>
        </Dropdown>
      </Space>
    </AntHeader>
  );
};

export default Header;
