// ============================================================
// Artifacts API — 产物管理（含 W23-24 版本管理）
// ============================================================

import { http } from './http';

export interface ArtifactMeta {
  id: string;
  task_id: string | null;
  artifact_type: string;
  file_path: string;
  version: number;
  parent_artifact_id: string | null;
  metadata: Record<string, unknown>;
  created_by_agent: string | null;
  created_at: string;
}

export interface ArtifactListResponse {
  artifacts: ArtifactMeta[];
  count: number;
}

export interface ArtifactVersionChain {
  artifact_id: string;
  versions: ArtifactMeta[];
  count: number;
  current_version: number;
}

export interface ArtifactDiffResponse {
  diff: string;
  base_id: string;
  target_id: string;
}

export interface RollbackResponse {
  artifact_id: string;
  rolled_back_from: string;
  artifact: ArtifactMeta;
  message: string;
}

/** 获取 Artifact 列表 */
export async function listArtifacts(params?: {
  task_id?: string;
  limit?: number;
  offset?: number;
}): Promise<ArtifactListResponse> {
  return http.get<ArtifactListResponse>('/artifacts', params);
}

/** 获取单个 Artifact 元数据 */
export async function getArtifact(id: string): Promise<ArtifactMeta> {
  return http.get<ArtifactMeta>(`/artifacts/${id}`);
}

/** 获取 Artifact 内容（纯文本） */
export async function getArtifactContent(id: string): Promise<string> {
  const res = await fetch(`/api/v1/artifacts/${id}/content`);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.text();
}

/** 创建 Artifact */
export async function createArtifact(body: {
  task_id: string;
  artifact_type: string;
  content: string;
  metadata?: Record<string, unknown>;
  parent_artifact_id?: string;
}): Promise<{ artifact_id: string; artifact: ArtifactMeta }> {
  return http.post('/artifacts', body);
}

/** 删除 Artifact */
export async function deleteArtifact(id: string): Promise<{ deleted: string }> {
  return http.delete<{ deleted: string }>(`/artifacts/${id}`);
}

// ── 版本管理（W23-24）────────────────────────────────────────

/** 获取完整版本链（从最旧到最新） */
export async function getArtifactVersions(id: string): Promise<ArtifactVersionChain> {
  return http.get<ArtifactVersionChain>(`/artifacts/${id}/versions`);
}

/** 基于已有 Artifact 创建新版本 */
export async function createArtifactVersion(
  parentId: string,
  content: string,
  metadata?: Record<string, unknown>,
): Promise<{ artifact_id: string; artifact: ArtifactMeta }> {
  return http.post(`/artifacts/${parentId}/versions`, { content, metadata });
}

/** Diff 两个 Artifact 版本（返回 unified diff 字符串） */
export async function diffArtifacts(
  targetId: string,
  compareWithId: string,
): Promise<ArtifactDiffResponse> {
  return http.get<ArtifactDiffResponse>(`/artifacts/${targetId}/diff`, {
    compare_with: compareWithId,
  } as Record<string, string>);
}

/** 回滚到指定版本（创建新版本，内容同目标版本） */
export async function rollbackArtifact(
  artifactId: string,
  targetVersionId: string,
): Promise<RollbackResponse> {
  return http.post<RollbackResponse>(`/artifacts/${artifactId}/rollback`, {
    target_version_id: targetVersionId,
  });
}
