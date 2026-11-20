// ============================================================
// api/pipelines.ts — Pipeline 数据请求
// ============================================================

import { http } from './http';
import type { PipelineTemplate, PipelineRun } from '../types/pipeline';

/** 模板列表 */
export async function fetchTemplates(): Promise<PipelineTemplate[]> {
  return http.get<PipelineTemplate[]>('/pipelines/templates');
}

/** 创建模板 */
export async function createTemplate(body: Partial<PipelineTemplate>): Promise<PipelineTemplate> {
  return http.post<PipelineTemplate>('/pipelines/templates', body);
}

/** 更新模板 */
export async function updateTemplate(templateId: string, body: Partial<PipelineTemplate>): Promise<PipelineTemplate> {
  return http.put<PipelineTemplate>(`/pipelines/templates/${templateId}`, body);
}

/** 执行记录列表 */
export async function fetchRuns(params?: {
  template_id?: string;
  status?: string;
}): Promise<PipelineRun[]> {
  return http.get<PipelineRun[]>('/pipelines/runs', params as Record<string, string | number | undefined>);
}

/** 启动流程 */
export async function startPipeline(templateId: string): Promise<PipelineRun> {
  return http.post<PipelineRun>(`/pipelines/start`, { template_id: templateId });
}

/** 暂停运行 */
export async function pauseRun(runId: string): Promise<PipelineRun> {
  return http.put<PipelineRun>(`/pipelines/runs/${runId}/pause`);
}

/** 恢复运行 */
export async function resumeRun(runId: string): Promise<PipelineRun> {
  return http.put<PipelineRun>(`/pipelines/runs/${runId}/resume`);
}

/** 获取 Pipeline 列表（Runs） */
export async function fetchPipelines(): Promise<PipelineRun[]> {
  return http.get<PipelineRun[]>('/pipelines');
}

/** 获取模板详情 */
export async function fetchTemplate(templateId: string): Promise<PipelineTemplate> {
  return http.get<PipelineTemplate>(`/pipelines/templates/${templateId}`);
}

/** 获取运行详情 */
export async function fetchRun(runId: string): Promise<PipelineRun> {
  return http.get<PipelineRun>(`/pipelines/runs/${runId}`);
}
