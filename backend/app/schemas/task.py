"""
AI Runtime OS — Task Schema
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---- 基础字段 ----
class TaskBase(BaseModel):
    name: str = Field(max_length=255)
    goal_description: str = ""
    title: str = ""
    priority: str = Field(default="medium", pattern=r"^(critical|high|medium|low)$")
    tags: list[str] = Field(default_factory=list)
    issue_id: str | None = None       # 关联 Issue
    parent_task_id: str | None = None  # 父子任务


# ---- 创建 ----
class TaskCreate(TaskBase):
    """创建 Task"""
    agent_id: str | None = None   # Agent ID (UUID string)
    issue_id: str | None = None
    parent_task_id: str | None = None
    pass


# ---- 更新（全可选） ----
class TaskUpdate(BaseModel):
    """更新 Task（全可选）"""
    name: str | None = None
    goal_description: str | None = None
    title: str | None = None
    status: str | None = None
    kanban_column: str | None = None
    priority: str | None = None
    tags: list[str] | None = None
    agent_id: str | None = None
    issue_id: str | None = None
    parent_task_id: str | None = None


# ---- 响应 ----
class TaskResponse(TaskBase):
    """Task 响应"""
    id: str
    status: str = "pending"
    kanban_column: str = "todo"
    agent_id: str | None = None
    agent_name: str = ""
    issue_id: str | None = None
    parent_task_id: str | None = None

    # 时间戳
    created_at: str = ""
    updated_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None

    # 统计
    duration: int = 0       # ms
    token_usage: int = 0
    cost: float = 0.0

    # 工作流
    workflow_graph: dict | None = None

    model_config = ConfigDict(from_attributes=True)
