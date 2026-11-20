"""
AI Runtime OS — Agent 模型
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import ARRAY

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class Agent(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="developer",
        comment="architect | developer | tester | reviewer | deployer",
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="idle",
        comment="running | idle | error | offline",
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="gpt-4o")
    model_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bound",
        comment="bound=强制使用指定模型, auto=自动路由选择模型",
    )
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="自定义系统提示词，为空则使用角色默认提示词",
    )

    # Capability-based 能力标签
    capability_tags: Mapped[str] = mapped_column(
        String(512), nullable=False, default="",
        comment="逗号分隔的能力标签，如 code_generation,code_review",
    )

    # 配置
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    timeout_sec: Mapped[int] = mapped_column(Integer, default=300)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 统计（冗余字段，定时刷新）
    total_tasks: Mapped[int] = mapped_column(Integer, default=0)
    completed_tasks: Mapped[int] = mapped_column(Integer, default=0)
    failed_tasks: Mapped[int] = mapped_column(Integer, default=0)
    avg_duration: Mapped[int] = mapped_column(Integer, default=0, comment="平均耗时 ms")
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
