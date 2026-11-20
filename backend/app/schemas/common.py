"""
AI Runtime OS — 通用 Pydantic 模型
"""
from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    """分页查询参数"""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应"""
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class StatCard(BaseModel):
    """统计卡片"""
    key: str
    title: str
    value: int | str
    suffix: str = ""
    trend: float = 0.0
    trend_label: str = "较上周"
    color: str = "#1677ff"


class ActivityItem(BaseModel):
    """活动条目"""
    id: str
    type: str
    title: str
    description: str
    agent_name: str = ""
    timestamp: str
    status: str
