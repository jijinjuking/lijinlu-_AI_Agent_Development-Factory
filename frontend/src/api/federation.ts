/**
 * Federation API - 运行时联邦 API 层
 */
import { get, post, put, del } from './http';

export interface FederationMember {
  member_id: string;
  name: string;
  address: string;
  status: 'online' | 'offline' | 'syncing';
  runtime_version: string;
  capabilities: string[];
  joined_at: string;
  last_seen: string;
}

export interface FederationSyncStatus {
  member_id: string;
  last_sync: string;
  sync_status: 'idle' | 'syncing' | 'error';
  pending_items: number;
  error_message?: string;
}

// 后端返回 {"members": [...], "total": N}
export async function fetchMembers(): Promise<FederationMember[]> {
  const res = await get<{ members: FederationMember[]; total: number }>('/federation/members');
  return Array.isArray(res) ? res : (res?.members ?? []);
}

export async function addMember(data: {
  name: string;
  address: string;
  token?: string;
}): Promise<FederationMember> {
  return post<FederationMember>('/federation/members/join', data);
}

export async function removeMember(memberId: string): Promise<void> {
  await del(`/federation/members/${memberId}`);
}

// 后端返回 array
export async function fetchSyncStatuses(): Promise<FederationSyncStatus[]> {
  const res = await get<FederationSyncStatus[] | { statuses: FederationSyncStatus[] }>('/federation/sync-status');
  if (Array.isArray(res)) return res;
  return (res as any)?.statuses ?? [];
}

export async function triggerSync(memberId?: string): Promise<void> {
  if (memberId) {
    await post(`/federation/sync?target_member_id=${memberId}&source_member_id=local`);
  } else {
    await post(`/federation/sync/broadcast?source_member_id=local`);
  }
}

export async function fetchFederationConfig(): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>('/federation/policy');
}

export async function updateFederationConfig(data: Record<string, unknown>): Promise<Record<string, unknown>> {
  return put<Record<string, unknown>>('/federation/policy', data);
}

// ── Store shim ─────────────────────────────────────────────────────────

export type { FederationSyncStatus as SyncStatus };

export const fetchSyncStatus = fetchSyncStatuses;
export const syncNow = triggerSync;
