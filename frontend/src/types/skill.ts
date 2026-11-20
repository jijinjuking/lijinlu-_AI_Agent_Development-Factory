// ============================================================
// Skill 相关类型定义
// ============================================================

export interface Skill {
  id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  installed: boolean;
  version?: string;
  author?: string;
  created_at: string;
  updated_at: string;
}
