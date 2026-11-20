// ============================================================
// Sidebar — 左侧导航菜单
// ============================================================

import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Layout, Menu } from 'antd';
import {
  DashboardOutlined,
  RobotOutlined,
  NodeIndexOutlined,
  EyeOutlined,
  DatabaseOutlined,
  AppstoreOutlined,
  DollarOutlined,
  SettingOutlined,
  FileProtectOutlined,
  FolderOutlined,
  ToolOutlined,
  SearchOutlined,
  PlayCircleOutlined,
  HistoryOutlined,
  StarOutlined,
  UnorderedListOutlined,
  ThunderboltOutlined,
  CloudServerOutlined,
  ApartmentOutlined,
  ShopOutlined,
  GlobalOutlined,
  TeamOutlined,
  RocketOutlined,
  ProjectOutlined,
  BugOutlined,
} from '@ant-design/icons';

const { Sider } = Layout;

interface SidebarProps {
  collapsed: boolean;
  theme: 'light' | 'dark';
}

/** 菜单项配置 */
const menuItems = [
  {
    key: '/',
    icon: <DashboardOutlined />,
    label: '仪表盘',
  },
  {
    key: '/agents',
    icon: <RobotOutlined />,
    label: 'Agent 看板',
  },
  {
    key: '/tasks',
    icon: <UnorderedListOutlined />,
    label: '任务管理',
  },
  {
    key: '/pipelines',
    icon: <NodeIndexOutlined />,
    label: '流程编排',
  },
  {
    key: '/traces',
    icon: <EyeOutlined />,
    label: 'Trace 追踪',
  },
  {
    key: '/events',
    icon: <ThunderboltOutlined />,
    label: '事件总线',
  },
  {
    key: '/event-replay',
    icon: <PlayCircleOutlined />,
    label: '事件回放',
  },
  {
    key: '/state-replay',
    icon: <HistoryOutlined />,
    label: 'State 回放',
  },
  {
    key: '/runtime-ops',
    icon: <CloudServerOutlined />,
    label: '运行时运维',
  },
  {
    key: '/k8s',
    icon: <CloudServerOutlined />,
    label: 'K8s 调度',
  },
  {
    key: '/multi-node',
    icon: <ApartmentOutlined />,
    label: '多节点调度',
  },
  {
    key: '/federation',
    icon: <GlobalOutlined />,
    label: '运行时联邦',
  },
  {
    key: '/evaluation',
    icon: <StarOutlined />,
    label: '质量评估',
  },
  {
    key: '/marketplace',
    icon: <ShopOutlined />,
    label: '能力市场',
  },
  {
    key: '/memory',
    icon: <DatabaseOutlined />,
    label: '记忆管理',
  },
  {
    key: '/skills',
    icon: <AppstoreOutlined />,
    label: 'Skill 市场',
  },
  {
    key: '/tenants',
    icon: <TeamOutlined />,
    label: '多租户',
  },
  {
    key: '/tools',
    icon: <ToolOutlined />,
    label: 'Tool Runtime',
  },
  {
    key: '/context',
    icon: <SearchOutlined />,
    label: 'Context Engine',
  },
  {
    key: '/artifacts',
    icon: <FolderOutlined />,
    label: 'Artifact 产物',
  },
  {
    key: '/state',
    icon: <FileProtectOutlined />,
    label: 'State 管理',
  },
  {
    key: '/projects',
    icon: <ProjectOutlined />,
    label: '项目管理',
  },
  {
    key: '/issues',
    icon: <BugOutlined />,
    label: 'Issue 跟踪',
  },
  {
    key: '/costs',
    icon: <DollarOutlined />,
    label: '成本分析',
  },
  {
    key: '/performance',
    icon: <RocketOutlined />,
    label: '性能监控',
  },
  {
    key: '/settings',
    icon: <SettingOutlined />,
    label: '系统设置',
  },
];

const Sidebar: React.FC<SidebarProps> = ({ collapsed, theme }) => {
  const navigate = useNavigate();
  const location = useLocation();

  const selectedKey = '/' + location.pathname.split('/')[1] || '/';

  return (
    <Sider
      collapsible
      collapsed={collapsed}
      trigger={null}
      width={220}
      style={{
        overflow: 'auto',
        height: '100vh',
        borderRight: theme === 'dark' ? '1px solid #30363d' : '1px solid #f0f0f0',
      }}
    >
      {/* Logo */}
      <div
        style={{
          height: 56,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          borderBottom: theme === 'dark' ? '1px solid #30363d' : '1px solid #f0f0f0',
        }}
      >
        <span
          style={{
            fontSize: collapsed ? 18 : 16,
            fontWeight: 700,
            color: theme === 'dark' ? '#e6edf3' : '#001529',
            whiteSpace: 'nowrap',
            letterSpacing: 1,
          }}
        >
          {collapsed ? 'AI' : 'AI Agent OS'}
        </span>
      </div>

      <Menu
        theme={theme === 'dark' ? 'dark' : 'light'}
        mode="inline"
        selectedKeys={[selectedKey]}
        items={menuItems}
        onClick={({ key }) => navigate(key)}
        style={{ borderRight: 0, marginTop: 8 }}
      />
    </Sider>
  );
};

export default Sidebar;
