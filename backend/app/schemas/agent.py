"""
AI Runtime OS — Agent Schema
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AgentBase(BaseModel):
    name: str = Field(max_length=128)
    role: str = Field(default="developer")
    model: str = Field(default="gpt-4o")
    model_mode: str = Field(default="bound", pattern=r"^(bound|auto)$")
    description: str = ""
    system_prompt: str | None = None
    capability_tags: str = ""
    max_retries: int = 3
    timeout_sec: int = 300
    is_active: bool = True


class AgentCreate(AgentBase):
    """创建 Agent"""
    pass


class AgentUpdate(BaseModel):
    """更新 Agent（全可选）"""
    role: str | None = None
    model: str | None = None
    model_mode: str | None = Field(default=None, pattern=r"^(bound|auto)$")
    description: str | None = None
    system_prompt: str | None = None
    capability_tags: str | None = None
    max_retries: int | None = None
    timeout_sec: int | None = None
    is_active: bool | None = None


class AgentResponse(AgentBase):
    """Agent 响应"""
    id: str
    status: str = "idle"
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    avg_duration: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    created_at: str = ""
    last_active_at: str = ""

    model_config = ConfigDict(from_attributes=True)


class AgentStatusUpdate(BaseModel):
    """Agent 状态更新"""
    status: str = Field(pattern=r"^(running|idle|error|offline)$")
