// ============================================================
// api/skills.ts — Skills 数据请求
// ============================================================

import { http } from './http';
import type { Skill } from '../types/skill';

export async function fetchSkills(params?: {
  category?: string;
  installed?: string;
  q?: string;
}): Promise<Skill[]> {
  return http.get<Skill[]>('/skills', params as Record<string, string | number | undefined>);
}

export async function installSkill(id: string): Promise<Skill> {
  return http.post<Skill>(`/skills/${id}/install`);
}

export async function uninstallSkill(id: string): Promise<Skill> {
  return http.post<Skill>(`/skills/${id}/uninstall`);
}

/** 获取单个 Skill 详情 */
export async function fetchSkill(id: string): Promise<Skill> {
  return http.get<Skill>(`/skills/${id}`);
}
