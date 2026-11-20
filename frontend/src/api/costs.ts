// ============================================================
// api/costs.ts — Costs 数据请求
// ============================================================

import { http } from './http';

export interface CostSummary {
  today_cost: number;
  week_cost: number;
  month_cost: number;
  total_cost: number;
  today_tokens: number;
  total_tokens: number;
}

export interface CostRecord {
  id: string;
  agent_name: string;
  model: string;
  tokens: number;
  cost: number;
  created_at: string;
}

export interface CostTrendItem {
  date: string;
  cost: number;
  tokens: number;
}

export async function fetchCostSummary(): Promise<CostSummary> {
  return http.get<CostSummary>('/costs/summary');
}

export async function fetchCostRecords(params: {
  page: number;
  page_size: number;
}): Promise<{ list: CostRecord[]; total: number }> {
  return http.get<{ list: CostRecord[]; total: number }>('/costs/records', params as Record<string, string | number | undefined>);
}

export async function fetchCostByModel(): Promise<{ model: string; cost: number; tokens: number }[]> {
  return http.get<any>('/costs/by-model').then(r => r.data ?? r);
}

export async function fetchCostByAgent(): Promise<{ agent_name: string; cost: number; tokens: number }[]> {
  return http.get<any>('/costs/by-agent').then(r => r.data ?? r);
}

export async function fetchCostTrend(days = 7): Promise<CostTrendItem[]> {
  return http.get<CostTrendItem[]>('/costs/trend', { days });
}

/** 模型定价信息 */
export interface ModelPricing {
  model: string;
  provider: string;
  input_price: number;
  output_price: number;
}
export async function fetchModelPricing(): Promise<ModelPricing[]> {
  return http.get<ModelPricing[]>('/costs/pricing');
}
