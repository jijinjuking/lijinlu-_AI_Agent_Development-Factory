// ============================================================
// routes — 路由配置
// ============================================================

import React, { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { Spin } from 'antd';
import AppLayout from './components/layout/AppLayout';
import LoginPage from './pages/LoginPage';

// 懒加载页面
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const AgentsPage = lazy(() => import('./pages/AgentsPage'));
const PipelinesPage = lazy(() => import('./pages/PipelinesPage'));
const TracesPage = lazy(() => import('./pages/TracesPage'));
const MemoryPage = lazy(() => import('./pages/MemoryPage'));
const SkillsPage = lazy(() => import('./pages/SkillsPage'));
const CostsPage = lazy(() => import('./pages/CostsPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const StateManagerPage = lazy(() => import('./pages/StateManagerPage'));
const ArtifactsPage = lazy(() => import('./pages/ArtifactsPage'));
const ToolsPage = lazy(() => import('./pages/ToolsPage'));
const ContextPage = lazy(() => import('./pages/ContextPage'));
const EventReplayPage = lazy(() => import('./pages/EventReplayPage'));
const StateReplayPage = lazy(() => import('./pages/StateReplayPage'));
// Phase A1 核心页面
const TasksPage = lazy(() => import('./pages/TasksPage'));
const EventsPage = lazy(() => import('./pages/EventsPage'));
const RuntimeOpsPage = lazy(() => import('./pages/RuntimeOpsPage'));
const EvaluationPage = lazy(() => import('./pages/EvaluationPage'));
// Phase A2 扩展页面
const K8sPage = lazy(() => import('./pages/K8sPage'));
const MultiNodePage = lazy(() => import('./pages/MultiNodePage'));
const MarketplacePage = lazy(() => import('./pages/MarketplacePage'));
const FederationPage = lazy(() => import('./pages/FederationPage'));
const TenantPage = lazy(() => import('./pages/TenantPage'));
const PerformancePage = lazy(() => import('./pages/PerformancePage'));
const ProjectsPage = lazy(() => import('./pages/ProjectsPage'));
const IssuesPage = lazy(() => import('./pages/IssuesPage'));
const IssueDetailPage = lazy(() => import('./pages/IssueDetailPage'));
const WebSocketTestPage = lazy(() => import('./pages/WebSocketTest'));

/** 页面加载 Suspense */
function LazyPage({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 80 }}>
          <Spin size="large" description="加载中..." />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

/** 路由表 */
export const router = createBrowserRouter([
  // 登录页（无需认证，独立布局）
  {
    path: '/login',
    element: <LoginPage />,
  },
  // 主应用布局（需要认证，由 AppLayout 内部守卫）
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <LazyPage><DashboardPage /></LazyPage> },
      { path: 'agents', element: <LazyPage><AgentsPage /></LazyPage> },
      { path: 'pipelines', element: <LazyPage><PipelinesPage /></LazyPage> },
      { path: 'traces', element: <LazyPage><TracesPage /></LazyPage> },
      { path: 'memory', element: <LazyPage><MemoryPage /></LazyPage> },
      { path: 'skills', element: <LazyPage><SkillsPage /></LazyPage> },
      { path: 'costs', element: <LazyPage><CostsPage /></LazyPage> },
      { path: 'settings', element: <LazyPage><SettingsPage /></LazyPage> },
      { path: 'state', element: <LazyPage><StateManagerPage /></LazyPage> },
      { path: 'artifacts', element: <LazyPage><ArtifactsPage /></LazyPage> },
      { path: 'tools', element: <LazyPage><ToolsPage /></LazyPage> },
      { path: 'context', element: <LazyPage><ContextPage /></LazyPage> },
      { path: 'event-replay', element: <LazyPage><EventReplayPage /></LazyPage> },
      { path: 'state-replay', element: <LazyPage><StateReplayPage /></LazyPage> },
      // Phase A1 核心页面
      { path: 'tasks', element: <LazyPage><TasksPage /></LazyPage> },
      { path: 'events', element: <LazyPage><EventsPage /></LazyPage> },
      { path: 'runtime-ops', element: <LazyPage><RuntimeOpsPage /></LazyPage> },
      { path: 'evaluation', element: <LazyPage><EvaluationPage /></LazyPage> },
      // Phase A2 扩展页面
      { path: 'k8s', element: <LazyPage><K8sPage /></LazyPage> },
      { path: 'multi-node', element: <LazyPage><MultiNodePage /></LazyPage> },
      { path: 'marketplace', element: <LazyPage><MarketplacePage /></LazyPage> },
      { path: 'federation', element: <LazyPage><FederationPage /></LazyPage> },
      { path: 'tenants', element: <LazyPage><TenantPage /></LazyPage> },
      { path: 'performance', element: <LazyPage><PerformancePage /></LazyPage> },
      { path: 'projects', element: <LazyPage><ProjectsPage /></LazyPage> },
      { path: 'issues', element: <LazyPage><IssuesPage /></LazyPage> },
      { path: 'issues/:issueId', element: <LazyPage><IssueDetailPage /></LazyPage> },
      { path: 'ws-test-react', element: <LazyPage><WebSocketTestPage /></LazyPage> },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
]);
