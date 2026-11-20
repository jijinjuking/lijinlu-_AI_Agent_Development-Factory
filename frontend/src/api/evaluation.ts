/**
 * Evaluation API - 评估系统 API 层
 * 对接后端 W18 Self Evaluation（自评估系统）
 */
import { get, post, del } from './http';

// ===== 对应后端真实 Schema =====

export interface EvaluationSummary {
  task_id: string;
  agent_name: string;
  overall_score: number;
  passed: boolean;
  issue_count: number;
  critical_count: number;
  major_count: number;
  evaluation_timestamp: string;
}

export interface EvaluationResponse {
  id: string;
  task_id: string;
  node_id: string;
  agent_id: string;
  agent_name: string;
  scope: string;
  overall_score: number;
  passed: boolean;
  threshold: number;
  dimension_scores: { metric: string; score: number; passed: boolean; reason: string }[];
  issues: { code: string; severity: string; message: string; suggestion?: string }[];
  suggestions: string[];
  execution_time_ms: number;
  evaluator_version: string;
  evaluation_timestamp: string;
  created_at: string;
  updated_at: string;
}

export interface EvaluationStats {
  total_evaluations: number;
  total_tasks_evaluated: number;
  average_score: number;
  pass_rate: number;
  total_issues_found: number;
  critical_issues_count: number;
  major_issues_count: number;
  top_improvement_areas: string[];
  score_distribution: Record<string, number>;
  dimension_averages: Record<string, number>;
}

// ===== 前端兼容类型（让 EvaluationPage.tsx 继续工作） =====
export type EvaluationRun = EvaluationSummary & {
  run_id: string;
  name: string;
  dataset_id: string;
  model_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'canceled';
  metrics: Record<string, number>;
  created_at: string;
  finished_at?: string;
  created_by: string;
  config?: Record<string, unknown>;
};

export interface EvaluationCase {
  case_id: string;
  dataset_id: string;
  input: string;
  expected_output?: string;
  context?: string[];
  metadata?: Record<string, unknown>;
  created_at: string;
}

export interface Dataset {
  dataset_id: string;
  name: string;
  description?: string;
  case_count: number;
  created_at: string;
  updated_at: string;
  created_by: string;
  tags?: string[];
}

export interface EvaluationMetric {
  metric_id: string;
  name: string;
  description: string;
  metric_type: 'accuracy' | 'relevance' | 'faithfulness' | 'custom';
  config?: Record<string, unknown>;
}

export type EvaluationStatus = EvaluationRun['status'];

// ===== API 方法 =====

function summaryToRun(s: EvaluationSummary): EvaluationRun {
  return {
    ...s,
    run_id: s.task_id,
    name: `${s.agent_name || 'Agent'} 评估`,
    dataset_id: '',
    model_id: s.agent_name || '',
    status: s.passed ? 'completed' : 'failed',
    metrics: { overall_score: s.overall_score },
    created_at: s.evaluation_timestamp || '',
    created_by: 'system',
  };
}

export async function fetchEvaluationRuns(params?: {
  task_id?: string;
  agent_name?: string;
  passed?: boolean;
  dataset_id?: string;
  model_id?: string;
  status?: EvaluationStatus;
  limit?: number;
  offset?: number;
}): Promise<EvaluationRun[]> {
  const query = new URLSearchParams();
  if (params?.task_id) query.set('task_id', params.task_id);
  if (params?.agent_name) query.set('agent_name', params.agent_name);
  if (params?.model_id) query.set('agent_name', params.model_id);
  if (params?.passed !== undefined) query.set('passed', String(params.passed));
  if (params?.status === 'completed') query.set('passed', 'true');
  if (params?.status === 'failed') query.set('passed', 'false');
  if (params?.limit) query.set('limit', String(params.limit));
  if (params?.offset) query.set('offset', String(params.offset));
  const qs = query.toString();
  const res = await get<EvaluationSummary[]>(`/evaluation/records${qs ? '?' + qs : ''}`);
  const arr = Array.isArray(res) ? res : [];
  return arr.map(summaryToRun);
}

export async function fetchEvaluationRun(runId: string): Promise<EvaluationRun> {
  const res = await get<EvaluationResponse>(`/evaluation/records/${runId}`);
  return summaryToRun({ ...res, issue_count: res.issues?.length ?? 0, critical_count: 0, major_count: 0 });
}

export async function createEvaluationRun(data: {
  name: string;
  dataset_id: string;
  model_id: string;
  config?: Record<string, unknown>;
}): Promise<EvaluationRun> {
  // 后端 POST /evaluation/evaluate 触发评估
  const res = await post<EvaluationResponse>('/evaluation/evaluate', {
    task_id: data.dataset_id || 'manual',
    scope: 'task',
    agent_name: data.model_id,
    context: { task_id: data.dataset_id || 'manual', agent_name: data.model_id, ...(data.config || {}) },
  });
  return summaryToRun({ ...res, issue_count: res.issues?.length ?? 0, critical_count: 0, major_count: 0 });
}

export async function updateEvaluationRun(
  runId: string,
  _data: Partial<Pick<EvaluationRun, 'name' | 'status' | 'config'>>
): Promise<EvaluationRun> {
  // 后端没有 update 端点，返回现有记录
  return fetchEvaluationRun(runId);
}

export async function deleteEvaluationRun(runId: string): Promise<void> {
  await del(`/evaluation/records/${runId}`);
}

export async function cancelEvaluationRun(_runId: string): Promise<void> {
  // 后端没有 cancel 端点
}

export async function rerunEvaluation(runId: string): Promise<EvaluationRun> {
  return fetchEvaluationRun(runId);
}

// ===== Results =====

export async function fetchEvaluationResults(runId: string): Promise<EvaluationResponse[]> {
  const res = await get<EvaluationSummary[]>(`/evaluation/task/${runId}`);
  return Array.isArray(res) ? (res as unknown as EvaluationResponse[]) : [];
}

export async function fetchEvaluationResult(resultId: string): Promise<EvaluationResponse> {
  return get<EvaluationResponse>(`/evaluation/records/${resultId}`);
}

// ===== Datasets =====

export async function fetchDatasets(params?: {
  tags?: string[];
  limit?: number;
  offset?: number;
}): Promise<Dataset[]> {
  const q = new URLSearchParams();
  if (params?.limit) q.set('limit', String(params.limit));
  if (params?.offset) q.set('offset', String(params.offset));
  const qs = q.toString();
  const res = await get<Dataset[]>(`/evaluation/datasets${qs ? '?' + qs : ''}`);
  return Array.isArray(res) ? res : [];
}

export async function fetchDataset(datasetId: string): Promise<Dataset> {
  return get<Dataset>(`/evaluation/datasets/${datasetId}`);
}

export async function createDataset(data: {
  name: string;
  description?: string;
  tags?: string[];
}): Promise<Dataset> {
  return post<Dataset>('/evaluation/datasets', data);
}

export async function updateDataset(
  datasetId: string,
  data: Partial<Pick<Dataset, 'name' | 'description' | 'tags'>>
): Promise<Dataset> {
  const res = await fetch(`/api/v1/evaluation/datasets/${datasetId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

export async function deleteDataset(datasetId: string): Promise<void> {
  await del(`/evaluation/datasets/${datasetId}`);
}

// ===== Cases =====

export async function fetchEvaluationCases(datasetId: string, params?: {
  limit?: number;
  offset?: number;
}): Promise<EvaluationCase[]> {
  const q = new URLSearchParams();
  q.set('dataset_id', datasetId);
  if (params?.limit) q.set('limit', String(params.limit));
  if (params?.offset) q.set('offset', String(params.offset));
  const res = await get<EvaluationCase[]>(`/evaluation/cases?${q.toString()}`);
  return Array.isArray(res) ? res : [];
}

export async function createEvaluationCase(
  datasetId: string,
  data: Omit<EvaluationCase, 'case_id' | 'dataset_id' | 'created_at'>
): Promise<EvaluationCase> {
  return post<EvaluationCase>('/evaluation/cases', { ...data, dataset_id: datasetId });
}

export async function updateEvaluationCase(
  caseId: string,
  data: Partial<Omit<EvaluationCase, 'case_id' | 'dataset_id' | 'created_at'>>
): Promise<EvaluationCase> {
  const res = await fetch(`/api/v1/evaluation/cases/${caseId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

export async function deleteEvaluationCase(caseId: string): Promise<void> {
  await del(`/evaluation/cases/${caseId}`);
}

export async function batchCreateCases(
  datasetId: string,
  cases: Omit<EvaluationCase, 'case_id' | 'dataset_id' | 'created_at'>[]
): Promise<{ created: number; errors: string[] }> {
  const result = await post<{ created: number; errors: string[] }>('/evaluation/cases/batch', {
    dataset_id: datasetId,
    cases,
  });
  return result;
}

// ===== Metrics =====

export async function fetchMetrics(): Promise<EvaluationMetric[]> {
  // 从 stats 里提取 dimension_averages 作为指标列表
  try {
    const stats = await get<EvaluationStats>('/evaluation/stats');
    return Object.keys(stats.dimension_averages || {}).map((k) => ({
      metric_id: k,
      name: k,
      description: k,
      metric_type: 'custom' as const,
    }));
  } catch {
    return [];
  }
}

export async function computeMetrics(_runId: string, _metricIds: string[]): Promise<Record<string, number>> {
  return {};
}

// ===== Comparison =====

export async function compareRuns(
  runIds: string[]
): Promise<{ runs: EvaluationRun[]; comparison: Record<string, unknown> }> {
  const runs = await Promise.all(runIds.map((id) => fetchEvaluationRun(id).catch(() => null)));
  const valid = runs.filter(Boolean) as EvaluationRun[];
  const comparison: Record<string, unknown> = {};
  valid.forEach((r) => { comparison[r.run_id] = r.metrics; });
  return { runs: valid, comparison };
}

// ── Store shims ────────────────────────────────────────────────────────

export type EvaluationRecord = EvaluationRun;
export type EvaluationResult = EvaluationResponse;

export const fetchRecords = fetchEvaluationRuns;
export const fetchRecordDetail = fetchEvaluationRun;

export interface EvaluationMetrics {
  run_id: string;
  metrics: Record<string, number>;
  overall_score: number;
  passed: boolean;
}

export type EvaluationComparison = { runs: EvaluationRun[]; comparison: Record<string, unknown> };

export { compareRuns as fetchComparison };
export { rerunEvaluation as triggerEvaluation };
