// ============================================================
// Memory 相关类型定义
// ============================================================

export interface MemoryEntry {
  id: string;
  layer: 'project' | 'user' | 'cloud';
  source: string;
  content: string;
  importance: number;       // 1-10
  tags: string[];
  created_at: string;
  updated_at: string;
}
