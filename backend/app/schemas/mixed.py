"""
AI Runtime OS — Skill + Memory + Cost + Settings Schema
合并为单文件避免碎片化（< 200 行）
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ---- Skill ----

class SkillResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    category: str = "code"
    icon: str = "CodeOutlined"
    author: str = ""
    version: str = "1.0.0"
    downloads: int = 0
    rating: float = 0.0
    installed: bool = False
    size: str = "0 MB"
    tags: list[str] = Field(default_factory=list)
    updated_at: str = ""
    requires_config: bool = False
    config_fields: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# ---- Memory ----

class MemoryResponse(BaseModel):
    id: str
    layer: str
    title: str
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    source: str = "手动设置"
    importance: str = "medium"
    token_estimate: int = 0

    model_config = ConfigDict(from_attributes=True)


class MemoryCreate(BaseModel):
    layer: str = Field(pattern=r"^(cloud|user|project)$")
    title: str = Field(max_length=255)
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    importance: str = Field(default="medium", pattern=r"^(high|medium|low)$")


class MemoryStats(BaseModel):
    cloud_count: int = 0
    user_count: int = 0
    project_count: int = 0
    total_tokens: int = 0


# ---- Cost ----

class CostSummaryResponse(BaseModel):
    today_cost: float = 0.0
    week_cost: float = 0.0
    month_cost: float = 0.0
    total_cost: float = 0.0
    today_tokens: int = 0
    month_tokens: int = 0
    total_tokens: int = 0
    top_agent: str = ""
    top_agent_cost: float = 0.0


class CostRecordResponse(BaseModel):
    id: str
    date: str
    agent_id: str = ""
    agent_name: str = ""
    model: str
    task_type: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    duration: int = 0


class ModelCostSummaryResponse(BaseModel):
    model: str
    total_tokens: int = 0
    total_cost: float = 0.0
    call_count: int = 0
    percentage: float = 0.0


class AgentCostSummaryResponse(BaseModel):
    agent_id: str
    agent_name: str
    total_tokens: int = 0
    total_cost: float = 0.0
    task_count: int = 0


class CostTrendResponse(BaseModel):
    date: str
    cost: float
    tokens: int


class ModelPricingResponse(BaseModel):
    model: str
    provider: str
    input_price: float
    output_price: float


# ---- Settings ----

class ModelConfigResponse(BaseModel):
    id: str
    name: str
    model_id: str = ""
    provider: str
    endpoint: str = ""
    api_base: str = ""
    api_key_id: str | None = None
    api_key_label: str = ""  # 前端展示用，从 api_keys 表 JOIN
    enabled: bool = True
    default_for: list[str] = Field(default_factory=list)
    max_tokens: int = 128000
    temperature: float = 0.4
    cost_input_per_1k: float = 0.0
    cost_output_per_1k: float = 0.0
    api_key_configured: bool = False

    model_config = ConfigDict(from_attributes=True)


class ModelConfigCreate(BaseModel):
    name: str
    model_id: str = ""
    provider: str
    endpoint: str = ""
    api_base: str = ""
    api_key_id: str | None = None
    enabled: bool = True
    default_for: list[str] = Field(default_factory=list)
    max_tokens: int = 128000
    temperature: float = 0.4
    cost_input_per_1k: float = 0.0
    cost_output_per_1k: float = 0.0
    api_key_configured: bool = False


class ApiKeyResponse(BaseModel):
    id: str
    provider: str
    label: str
    masked_key: str
    created_at: str = ""
    last_used: str | None = None
    enabled: bool = True

    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreate(BaseModel):
    provider: str
    label: str
    key: str = Field(min_length=8)


class AgentPermissionResponse(BaseModel):
    id: str
    role_id: str
    role_name: str
    can_create_pipeline: bool = False
    can_deploy: bool = False
    can_access_network: bool = True
    can_write_files: bool = True
    can_execute_commands: bool = False
    max_concurrency: int = 2
    max_tokens_per_task: int = 30000
    max_daily_cost: float = 10.0

    model_config = ConfigDict(from_attributes=True)


class AgentPermissionUpdate(BaseModel):
    can_create_pipeline: bool | None = None
    can_deploy: bool | None = None
    can_access_network: bool | None = None
    can_write_files: bool | None = None
    can_execute_commands: bool | None = None
    max_concurrency: int | None = None
    max_tokens_per_task: int | None = None
    max_daily_cost: float | None = None
