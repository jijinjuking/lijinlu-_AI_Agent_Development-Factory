// ============================================================
// api/settings.ts — Settings 数据请求
// ============================================================

import { http } from './http';
import type { ModelConfig, ApiKey, AgentPermission, RuntimeSettings } from '../types/settings';

/** Models */
export async function fetchModels(): Promise<ModelConfig[]> {
  return http.get<ModelConfig[]>('/settings/models');
}
export async function createModel(body: Partial<ModelConfig>): Promise<ModelConfig> {
  return http.post<ModelConfig>('/settings/models', body);
}
export async function updateModel(id: string, body: Partial<ModelConfig>): Promise<ModelConfig> {
  return http.put<ModelConfig>(`/settings/models/${id}`, body);
}
export async function deleteModel(id: string): Promise<void> {
  return http.delete<void>(`/settings/models/${id}`);
}

/** API Keys */
export async function fetchApiKeys(): Promise<ApiKey[]> {
  return http.get<ApiKey[]>('/settings/api-keys');
}
export async function createApiKey(body: Partial<ApiKey>): Promise<ApiKey> {
  return http.post<ApiKey>('/settings/api-keys', body);
}
export async function deleteApiKey(id: string): Promise<void> {
  return http.delete<void>(`/settings/api-keys/${id}`);
}

/** Permissions */
export async function fetchPermissions(): Promise<AgentPermission[]> {
  return http.get<AgentPermission[]>('/settings/permissions');
}
export async function updatePermission(role_id: string, body: Partial<AgentPermission>): Promise<AgentPermission> {
  return http.put<AgentPermission>(`/settings/permissions/${role_id}`, body);
}

/** Runtime Settings（通用设置） */
export async function fetchRuntimeSettings(): Promise<RuntimeSettings> {
  return http.get<RuntimeSettings>('/settings/runtime');
}
export async function updateRuntimeSettings(body: Partial<RuntimeSettings>): Promise<RuntimeSettings> {
  return http.put<RuntimeSettings>('/settings/runtime', body);
}
