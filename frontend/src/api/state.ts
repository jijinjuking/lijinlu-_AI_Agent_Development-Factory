// ============================================================
// api/state.ts — State & Checkpoint API
// ============================================================

import { http } from './http';

// ── 类型定义 ──

export interface StateInfo {
  task_id: string;
  state: Record<string, unknown>;
  size_bytes: number;
  initialized?: boolean;
  warnings?: { field: string; message: string; current_size: number }[];
  restored?: boolean;
}

export interface StateSizeInfo {
  task_id: string;
  size_bytes: number;
  limit_bytes: number;
  percent: number;
  ok: boolean;
}

export interface CheckpointItem {
  id: string;
  task_id: string;
  created_at: string | null;
  event_seq_num: number | null;
  node: string;
  workflow_status: string;
  state_size: number;
}

export interface CheckpointList {
  task_id: string;
  checkpoints: CheckpointItem[];
  count: number;
}

export interface CheckpointDetail {
  id: string;
  task_id: string;
  created_at: string | null;
  event_seq_num: number | null;
  state_snapshot: Record<string, unknown>;
}

// ── State API ──

export async function getState(taskId: string): Promise<StateInfo> {
  return http.get<StateInfo>(`/state/${taskId}`);
}

export async function initializeState(taskId: string, goal?: string, projectId?: string): Promise<StateInfo> {
  const params = new URLSearchParams();
  if (goal) params.set('goal', goal);
  if (projectId) params.set('project_id', projectId);
  const qs = params.toString();
  return http.post<StateInfo>(`/state/${taskId}/initialize${qs ? '?' + qs : ''}`, undefined);
}

export async function updateState(taskId: string, updates: Record<string, unknown>): Promise<StateInfo> {
  return http.put<StateInfo>(`/state/${taskId}`, updates);
}

export async function getStateSize(taskId: string): Promise<StateSizeInfo> {
  return http.get<StateSizeInfo>(`/state/${taskId}/size`);
}

// ── Checkpoint API ──

export async function saveCheckpoint(taskId: string, eventSeqNum?: number): Promise<CheckpointItem> {
  const params = new URLSearchParams();
  if (eventSeqNum !== undefined) params.set('event_seq_num', String(eventSeqNum));
  const qs = params.toString();
  return http.post<CheckpointItem>(`/state/${taskId}/checkpoints${qs ? '?' + qs : ''}`);
}

export async function listCheckpoints(taskId: string): Promise<CheckpointList> {
  return http.get<CheckpointList>(`/state/${taskId}/checkpoints`);
}

export async function getLatestCheckpoint(taskId: string): Promise<CheckpointDetail> {
  return http.get<CheckpointDetail>(`/state/${taskId}/checkpoints/latest`);
}

export async function getCheckpointDetail(
  taskId: string,
  checkpointId: string,
): Promise<CheckpointDetail> {
  return http.get<CheckpointDetail>(`/state/${taskId}/checkpoints/${checkpointId}`);
}

export async function restoreCheckpoint(taskId: string, checkpointId: string): Promise<StateInfo> {
  return http.post<StateInfo>(`/state/${taskId}/checkpoints/${checkpointId}/restore`);
}

export async function deleteCheckpoint(taskId: string, checkpointId: string): Promise<void> {
  return http.delete<void>(`/state/${taskId}/checkpoints/${checkpointId}`);
}
