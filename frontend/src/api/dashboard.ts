// ============================================================
// api/dashboard.ts — Dashboard 数据请求
// ============================================================

import { http } from './http';
import type { StatCardData, RecentActivity } from '../types/common';

/** 后端 StatCard → 前端 StatCardData (snake_case → camelCase) */
interface BackendStatCard {
  key: string;
  title: string;
  value: number | string;
  suffix: string;
  trend: number;
  trend_label: string;
  color: string;
}

export async function fetchStats(): Promise<StatCardData[]> {
  const raw = await http.get<BackendStatCard[]>('/dashboard/stats');
  return raw.map((s) => ({
    key: s.key,
    title: s.title,
    value: s.value,
    suffix: s.suffix,
    trend: s.trend,
    trendLabel: s.trend_label,
    color: s.color,
  }));
}

/** 后端 ActivityItem → 前端 RecentActivity (snake_case → camelCase) */
interface BackendActivityItem {
  id: string;
  type: string;
  title: string;
  description: string;
  agent_name: string;
  timestamp: string;
  status: string;
}

const VALID_TYPES = new Set([
  'agent_start', 'agent_complete', 'pipeline_run', 'error', 'review',
  'llm_call', 'agent_event',
]);

export async function fetchActivities(): Promise<RecentActivity[]> {
  const raw = await http.get<BackendActivityItem[]>('/dashboard/activities');
  return raw.map((a) => {
    const type = VALID_TYPES.has(a.type)
      ? (a.type as RecentActivity['type'])
      : 'pipeline_run';
    const status = (
      a.status === 'success' || a.status === 'failed' || a.status === 'running'
    ) ? a.status : undefined;

    return {
      id: a.id,
      type,
      title: a.title,
      description: a.description,
      agentName: a.agent_name,
      timestamp: a.timestamp,
      status,
    };
  });
}
