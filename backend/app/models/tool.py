"""
AI Runtime OS — Tool 相关 ORM 模型
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime

from sqlalchemy import String, Integer, Boolean, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.sqlite import JSON

from app.models.base import Base, UUIDPrimaryKey, TimestampMixin, utcnow


class ToolDefinition(Base, UUIDPrimaryKey, TimestampMixin):
    """Tool 定义 — 注册到平台的工具元信息"""
    __tablename__ = "tool_definitions"

    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    adapter_type: Mapped[str] = mapped_column(String(64), default="shell")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    author: Mapped[str] = mapped_column(String(128), default="")
    tags: Mapped[str] = mapped_column(String(512), default="")
    parameters_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    sandbox_required: Mapped[bool] = mapped_column(Boolean, default=False)
    timeout_sec: Mapped[int] = mapped_column(Integer, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    permission_level: Mapped[str] = mapped_column(String(32), default="normal")


class ToolExecution(Base, UUIDPrimaryKey):
    """Tool 执行记录 — 审计追踪"""
    __tablename__ = "tool_executions"

    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending/running/completed/failed/timeout
    input_args: Mapped[dict] = mapped_column(JSON, default=dict)
    output_result: Mapped[str | None] = mapped_column(Text)
    output_error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    sandbox_id: Mapped[str | None] = mapped_column(String(128))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    token_usage: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
