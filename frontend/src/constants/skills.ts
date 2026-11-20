// ============================================================
// Skills / Skill 市场 常量 & 类型
// ============================================================

/** Skill 分类 */
export type SkillCategory = 'code' | 'data' | 'ops' | 'communication' | 'security' | 'media';

/** 分类标签 */
export const SKILL_CATEGORIES: Record<SkillCategory, string> = {
  code: '代码开发',
  data: '数据处理',
  ops: '运维部署',
  communication: '通信协作',
  security: '安全合规',
  media: '多媒体',
};

/** 分类颜色 */
export const SKILL_CATEGORY_COLORS: Record<SkillCategory, string> = {
  code: '#1677ff',
  data: '#52c41a',
  ops: '#13c2c2',
  communication: '#fa8c16',
  security: '#ff4d4f',
  media: '#722ed1',
};
