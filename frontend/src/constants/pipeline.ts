// ============================================================
// Pipeline / 流程编排 常量 & 类型
// ============================================================

/** Pipeline 步骤类型 */
export type StepType = 'agent' | 'condition' | 'parallel' | 'review' | 'deploy' | 'notify';

/** 步骤类型标签 */
export const STEP_TYPE_LABELS: Record<StepType, string> = {
  agent: 'Agent',
  condition: '条件判断',
  parallel: '并行执行',
  review: '人工审查',
  deploy: '部署',
  notify: '通知',
};

/** 步骤类型颜色 */
export const STEP_TYPE_COLORS: Record<StepType, string> = {
  agent: '#1677ff',
  condition: '#faad14',
  parallel: '#722ed1',
  review: '#fa8c16',
  deploy: '#13c2c2',
  notify: '#52c41a',
};

/** 分类标签 */
export const PIPELINE_CATEGORIES: Record<string, string> = {
  dev: '开发流程',
  ops: '运维流程',
  review: '审查流程',
  data: '数据处理',
  custom: '自定义',
};
