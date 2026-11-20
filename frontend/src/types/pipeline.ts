// ============================================================
// Pipeline 相关类型定义
// ============================================================

/** Pipeline 模板 */
export interface PipelineTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  steps: PipelineStep[];
  created_at: string;
  updated_at: string;
}

/** Pipeline 步骤 */
export interface PipelineStep {
  id: string;
  name: string;
  type: 'task' | 'approval' | 'condition' | 'parallel';
  agent_id?: string;
  config?: Record<string, unknown>;
  next_step_id?: string;
}

/** Pipeline 执行记录 */
export interface PipelineRun {
  id: string;
  template_id: string;
  template_name?: string;
  status: 'waiting' | 'running' | 'paused' | 'completed' | 'failed';
  current_step_id?: string;
  current_step_name?: string;
  progress: number;
  result?: string;
  error?: string;
  created_at: string;
  updated_at: string;
}
