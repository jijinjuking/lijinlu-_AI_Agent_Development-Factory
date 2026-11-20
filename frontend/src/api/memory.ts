// ============================================================
// api/memory.ts — Memory 数据请求
// ============================================================

import { http } from './http';
import type { MemoryEntry } from '../types/memory';

export async function fetchMemories(params?: {
  layer?: string;
  importance?: string;
  q?: string;
}): Promise<MemoryEntry[]> {
  return http.get<MemoryEntry[]>('/memory', params as Record<string, string | number | undefined>);
}

export async function fetchMemoryStats(): Promise<Record<string, number>> {
  return http.get<Record<string, number>>('/memory/stats');
}

export async function createMemory(body: Partial<MemoryEntry>): Promise<MemoryEntry> {
  return http.post<MemoryEntry>('/memory', body);
}

export async function deleteMemory(id: string): Promise<void> {
  return http.delete<void>(`/memory/${id}`);
}
