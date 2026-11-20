// ============================================================
// Settings 相关类型定义
// ============================================================

/** 模型配置 */
export interface ModelConfig {
  id: string;
  name: string;
  model_id: string;
  provider: string;
  api_base: string;
  api_key_id: string | null;
  api_key_label: string;
  enabled: boolean;
  default_for: string[];
  max_tokens: number;
  temperature: number;
  cost_input_per_1k: number;
  cost_output_per_1k: number;
  api_key_configured: boolean;
  created_at: string;
  updated_at: string;
}

/** API Key 配置 */
export interface ApiKey {
  id: string;
  provider: string;
  label: string;
  masked_key: string;
  created_at: string;
  updated_at: string;
}

/** Agent 角色权限配置（按角色控制能力边界） */
export interface AgentPermission {
  id: string;
  role_id: string;
  role_name: string;
  can_create_pipeline: boolean;
  can_deploy: boolean;
  can_access_network: boolean;
  can_write_files: boolean;
  can_execute_commands: boolean;
  max_concurrency: number;
  max_tokens_per_task: number;
  max_daily_cost: number;
}

/** 运行时配置（通用设置） */
export interface RuntimeSettings {
  max_concurrency: number;
  default_timeout_minutes: number;
  auto_retry_count: number;
  log_retention_days: number;
  notify_on_complete: boolean;
  notify_on_failure: boolean;
  cost_alert_threshold: number;
  notification_channels: string[];
}
