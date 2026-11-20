/**
 * Tenant API - 多租户系统 API 层
 * 后端 list_tenants 直接返回 list
 */
import { get, post, put, patch, del } from './http';

export type TenantStatus = 'active' | 'suspended' | 'pending';

export interface Tenant {
  tenant_id: string;
  name: string;
  status: TenantStatus;
  plan: 'free' | 'pro' | 'enterprise';
  resource_quota: {
    max_agents: number;
    max_tasks_per_day: number;
    max_storage_mb: number;
    max_concurrent_executions: number;
  };
  resource_usage: {
    agents: number;
    tasks_today: number;
    storage_mb: number;
    concurrent_executions: number;
  };
  created_at: string;
  owner_email: string;
}

export interface TenantUser {
  user_id: string;
  tenant_id: string;
  email: string;
  role: 'owner' | 'admin' | 'member' | 'viewer';
  status: 'active' | 'invited' | 'disabled';
  joined_at: string;
}

function toArray<T>(res: unknown): T[] {
  if (!res) return [];
  if (Array.isArray(res)) return res as T[];
  return ((res as any).items ?? (res as any).tenants ?? []) as T[];
}

export async function fetchTenants(params?: {
  status?: TenantStatus;
  plan?: string;
  limit?: number;
  offset?: number;
}): Promise<Tenant[]> {
  const q = new URLSearchParams();
  if (params?.status) q.set('status', params.status);
  if (params?.plan) q.set('plan', params.plan);
  if (params?.limit) q.set('limit', String(params.limit));
  if (params?.offset) q.set('offset', String(params.offset));
  const qs = q.toString();
  const res = await get<unknown>(`/tenants${qs ? '?' + qs : ''}`);
  return toArray<Tenant>(res);
}

export async function fetchTenant(tenantId: string): Promise<Tenant> {
  return get<Tenant>(`/tenants/${tenantId}`);
}

export async function createTenant(data: {
  name: string;
  plan?: 'free' | 'pro' | 'enterprise';
  owner_email: string;
}): Promise<Tenant> {
  return post<Tenant>('/tenants', data);
}

export async function updateTenant(tenantId: string, data: Partial<Tenant>): Promise<Tenant> {
  return patch<Tenant>(`/tenants/${tenantId}`, data);
}

export async function suspendTenant(tenantId: string): Promise<void> {
  await post(`/tenants/${tenantId}/suspend`);
}

export async function activateTenant(tenantId: string): Promise<void> {
  await post(`/tenants/${tenantId}/activate`);
}

export async function fetchTenantUsers(tenantId: string): Promise<TenantUser[]> {
  const res = await get<unknown>(`/tenants/${tenantId}/members`);
  return toArray<TenantUser>(res);
}

export async function inviteUser(tenantId: string, email: string, role: TenantUser['role']): Promise<void> {
  await post(`/tenants/${tenantId}/members`, { email, role });
}

// ── Store shims ────────────────────────────────────────────────────────

export const fetchTenantDetail = fetchTenant;

export async function deleteTenant(tenantId: string): Promise<void> {
  await post(`/tenants/${tenantId}/archive`);
}

export const fetchUsers = fetchTenantUsers;

export const addUser = inviteUser;

export async function removeUser(tenantId: string, userId: string): Promise<void> {
  await del(`/tenants/${tenantId}/members/${userId}`);
}

// ── 配额管理 ─────────────────────────────────────

export interface QuotaSummary {
  tenant_id: string;
  quotas: Record<string, { limit: number; used: number; remaining: number; status: string }>;
}

export async function fetchQuotaSummary(tenantId: string): Promise<QuotaSummary> {
  return get<QuotaSummary>(`/tenants/${tenantId}/quota`);
}

export async function setQuota(
  tenantId: string,
  resourceType: string,
  limit: number,
  alertThreshold = 0.8,
): Promise<void> {
  await post(`/tenants/${tenantId}/quota`, {
    resource_type: resourceType,
    limit,
    alert_threshold: alertThreshold,
  });
}

export async function allocateDefaultQuotas(tenantId: string, tier = 'standard'): Promise<void> {
  await post(`/tenants/${tenantId}/quota/defaults`, { tier });
}

export interface QuotaCheckResult {
  status: string;
}

export async function checkQuota(
  tenantId: string,
  resourceType: string,
  requested = 1,
): Promise<QuotaCheckResult> {
  return post<QuotaCheckResult>(`/tenants/${tenantId}/quota/check`, {
    resource_type: resourceType,
    requested,
  });
}

export async function consumeQuota(
  tenantId: string,
  resourceType: string,
  amount = 1,
): Promise<Record<string, unknown>> {
  return post<Record<string, unknown>>(`/tenants/${tenantId}/quota/consume`, {
    resource_type: resourceType,
    amount,
  });
}

export async function releaseQuota(
  tenantId: string,
  resourceType: string,
  amount = 1,
): Promise<void> {
  await post(`/tenants/${tenantId}/quota/release`, {
    resource_type: resourceType,
    amount,
  });
}

// ── 隔离与策略 ─────────────────────────────────

export interface IsolationInfo {
  isolation_mode: string;
  cross_tenant_policy: string;
  allowed_tenant_ids: string[];
  schema_name?: string;
}

export async function fetchIsolationInfo(tenantId: string): Promise<IsolationInfo> {
  return get<IsolationInfo>(`/tenants/${tenantId}/isolation`);
}

export async function checkCrossTenantAccess(
  sourceTenantId: string,
  targetTenantId: string,
): Promise<{ allowed: boolean }> {
  return post<{ allowed: boolean }>('/tenants/check-access', {
    source_tenant_id: sourceTenantId,
    target_tenant_id: targetTenantId,
  });
}

export async function grantCrossTenantAccess(
  tenantId: string,
  targetTenantId: string,
): Promise<void> {
  await post(`/tenants/${tenantId}/grant-access/${targetTenantId}`);
}

export async function revokeCrossTenantAccess(
  tenantId: string,
  targetTenantId: string,
): Promise<void> {
  await del(`/tenants/${tenantId}/grant-access/${targetTenantId}`);
}

// ── 审计 ───────────────────────────────────────

export interface AuditLogEntry {
  event_id: string;
  tenant_id: string;
  event_type: string;
  actor_id: string;
  actor_type: string;
  timestamp: string;
  detail: Record<string, unknown>;
}

export async function fetchAuditLogs(
  tenantId: string,
  params?: { limit?: number; offset?: number; event_type?: string },
): Promise<AuditLogEntry[]> {
  const q = new URLSearchParams();
  if (params?.limit) q.set('limit', String(params.limit));
  if (params?.offset) q.set('offset', String(params.offset));
  if (params?.event_type) q.set('event_type', params.event_type);
  const qs = q.toString();
  const res = await get<unknown>(`/tenants/${tenantId}/audit${qs ? '?' + qs : ''}`);
  return Array.isArray(res) ? res as AuditLogEntry[] : ((res as any).items ?? []) as AuditLogEntry[];
}

export async function fetchAuditTimeline(
  tenantId: string,
  limit = 50,
): Promise<Record<string, unknown>[]> {
  return get<Record<string, unknown>[]>(`/tenants/${tenantId}/audit/timeline`, { limit });
}

export async function fetchViolations(
  tenantId: string,
  limit = 100,
): Promise<Record<string, unknown>[]> {
  return get<Record<string, unknown>[]>(`/tenants/${tenantId}/audit/violations`, { limit });
}

// ── 统计 ───────────────────────────────────────

export interface TenantStats {
  tenant_id: string;
  agent_count: number;
  task_count: number;
  storage_mb: number;
  [key: string]: unknown;
}

export interface GlobalTenantStats {
  total_tenants: number;
  active_tenants: number;
  suspended_tenants: number;
  audit: Record<string, unknown>;
}

export async function fetchGlobalStats(): Promise<GlobalTenantStats> {
  return get<GlobalTenantStats>('/tenants/stats');
}

export async function fetchTenantStats(tenantId: string): Promise<TenantStats> {
  return get<TenantStats>(`/tenants/${tenantId}/stats`);
}
