"""
AI Runtime OS — Pipeline + Task Schema
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ---- Pipeline ----

class PipelineStepSchema(BaseModel):
    id: str
    name: str
    type: str  # agent | condition | parallel | review | deploy | notify
    agent_role: str = ""
    description: str = ""
    next_steps: list[str] = Field(default_factory=list)


class PipelineTemplateResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    icon: str = "CodeOutlined"
    category: str = "custom"
    tags: list[str] = Field(default_factory=list)
    steps: list[PipelineStepSchema] = Field(default_factory=list)
    avg_duration: int = 0
    success_rate: float = 0.0
    created_at: str = ""
    updated_at: str = ""

    model_config = ConfigDict(from_attributes=True)


class PipelineRunResponse(BaseModel):
    id: str
    template_id: str = ""
    template_name: str = ""
    status: str
    current_step_id: str = ""
    current_step_name: str = ""
    progress: float = 0.0
    result: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    # 兼容旧字段
    started_at: str = ""
    completed_at: str | None = None
    duration: int | None = None
    current_step: str | None = None
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    triggered_by: str = "手动触发"
    cost: float | None = None

    model_config = ConfigDict(from_attributes=True)


class PipelineTemplateCreate(BaseModel):
    """创建 Pipeline 模板请求"""
    name: str
    description: str = ""
    icon: str = "CodeOutlined"
    category: str = "custom"
    tags: list[str] = Field(default_factory=list)
    steps: list[PipelineStepSchema] = Field(default_factory=list)


class PipelineRunRequest(BaseModel):
    """启动 Pipeline 请求"""
    template_id: str
    params: dict = Field(default_factory=dict)


# ---- Task (Kanban) ----

class TaskBase(BaseModel):
    title: str = Field(max_length=255)
    priority: str = Field(default="medium")
    tags: list[str] = Field(default_factory=list)


class TaskCreate(TaskBase):
    agent_name: str = ""
    goal_description: str = ""


class TaskResponse(TaskBase):
    id: str
    agent_id: str = ""
    agent_name: str = ""
    status: str = "pending"
    kanban_column: str = "todo"
    token_usage: int = 0
    cost: float = 0.0
    started_at: str | None = None
    completed_at: str | None = None
    duration: int | None = None
    created_at: str = ""

    model_config = ConfigDict(from_attributes=True)


class KanbanColumnResponse(BaseModel):
    id: str
    type: str
    title: str
    tasks: list[TaskResponse] = Field(default_factory=list)
