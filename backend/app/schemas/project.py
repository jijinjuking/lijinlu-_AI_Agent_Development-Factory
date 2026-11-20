"""
AI Runtime OS — Project Schema
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---- 基础 ----
class ProjectBase(BaseModel):
    name: str = Field(max_length=255)
    description: str = ""
    status: str = Field(default="active", pattern=r"^(active|archived)$")


# ---- 创建 ----
class ProjectCreate(ProjectBase):
    pass


# ---- 更新 ----
class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = Field(default=None, pattern=r"^(active|archived)$")


# ---- 响应 ----
class ProjectResponse(ProjectBase):
    id: str
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""

    model_config = ConfigDict(from_attributes=True)
