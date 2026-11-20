/**
 * Marketplace API - AI 能力市场 API 层
 * 后端列表接口返回 { items: [...], total: N, page: N, page_size: N }
 */
import { get, post, put } from './http';

export type PackageType = 'skill' | 'agent' | 'workflow';
export type PackageStatus = 'draft' | 'pending_review' | 'published' | 'deprecated' | 'archived';

export interface MarketplacePackage {
  package_id: string;
  name: string;
  description: string;
  package_type: PackageType;
  version: string;
  author: string;
  tags: string[];
  status: PackageStatus;
  download_count: number;
  rating: number;
  rating_count: number;
  created_at: string;
  updated_at: string;
  install_url?: string;
}

export interface Rating {
  rating_id: string;
  package_id: string;
  user_id: string;
  score: number;
  comment?: string;
  created_at: string;
}

function toArray<T>(res: T[] | { items: T[]; total?: number } | null | undefined): T[] {
  if (!res) return [];
  if (Array.isArray(res)) return res;
  return (res as any).items ?? [];
}

export async function fetchPackages(params?: {
  package_type?: PackageType;
  tags?: string[];
  q?: string;
  limit?: number;
  offset?: number;
}): Promise<MarketplacePackage[]> {
  const q = new URLSearchParams();
  if (params?.package_type) q.set('type', params.package_type);
  if (params?.tags?.length) q.set('tags', params.tags.join(','));
  if (params?.q) q.set('q', params.q);
  if (params?.limit) q.set('limit', String(params.limit));
  if (params?.offset) q.set('offset', String(params.offset));
  const qs = q.toString();
  const res = await get<MarketplacePackage[] | { items: MarketplacePackage[] }>(`/marketplace/packages${qs ? '?' + qs : ''}`);
  return toArray(res);
}

export async function fetchPackage(packageId: string): Promise<MarketplacePackage> {
  return get<MarketplacePackage>(`/marketplace/packages/${packageId}`);
}

export async function publishPackage(data: {
  name: string;
  description: string;
  package_type: PackageType;
  version?: string;
  tags?: string[];
}): Promise<MarketplacePackage> {
  return post<MarketplacePackage>('/marketplace/packages', data);
}

export async function updatePackage(packageId: string, data: Partial<MarketplacePackage>): Promise<MarketplacePackage> {
  return put<MarketplacePackage>(`/marketplace/packages/${packageId}`, data);
}

export async function deprecatePackage(packageId: string): Promise<void> {
  await put(`/marketplace/packages/${packageId}/deprecate`);
}

export async function installPackage(packageId: string): Promise<void> {
  await post(`/marketplace/packages/${packageId}/install`);
}

export async function checkUpdates(): Promise<{ package_id: string; new_version: string }[]> {
  const res = await get<{ package_id: string; new_version: string }[] | { items: { package_id: string; new_version: string }[] }>('/marketplace/installed/check-updates');
  return toArray(res);
}

export async function fetchRatings(packageId: string): Promise<Rating[]> {
  const res = await get<Rating[] | { items: Rating[] }>(`/marketplace/packages/${packageId}/ratings`);
  return toArray(res);
}

export async function submitRating(packageId: string, score: number, comment?: string): Promise<Rating> {
  return post<Rating>(`/marketplace/packages/${packageId}/ratings`, { score, comment });
}

// ── Store shims ────────────────────────────────────────────────────────

export const fetchPackageDetail = fetchPackage;

export async function searchPackages(query: string): Promise<MarketplacePackage[]> {
  const params = new URLSearchParams();
  if (query) params.set('q', query);
  const qs = params.toString();
  const res = await get<any>(`/marketplace/packages${qs ? '?' + qs : ''}`);
  return toArray<MarketplacePackage>(res);
}

export async function uninstallPackage(packageId: string): Promise<void> {
  await post(`/marketplace/packages/${packageId}/uninstall`);
}
