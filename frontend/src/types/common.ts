// ============================================================
// 通用类型定义
// ============================================================

/** 主题模式 */
export type ThemeMode = 'light' | 'dark';

/** 统计卡片数据 */
export interface StatCardData {
  key: string;
  title: string;
  value: number | string;
  prefix?: string;
  suffix?: string;
  trend?: number; // 正数上涨，负数下跌
  trendLabel?: string;
  icon?: string;
  color?: string;
}

/** 最近活动 */
export interface RecentActivity {
  id: string;
  type: 'agent_start' | 'agent_complete' | 'pipeline_run' | 'error' | 'review' | 'llm_call' | 'agent_event';
  title: string;
  description: string;
  agentName?: string;
  timestamp: string;
  status?: 'success' | 'failed' | 'running';
}

/** API 响应包装 */
export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

/** 分页请求 */
export interface PaginationParams {
  page: number;
  pageSize: number;
}

/** 分页响应 */
export interface PaginatedData<T> {
  list: T[];
  total: number;
  page: number;
  pageSize: number;
}
