"""
AI Runtime OS — Pipeline 模板 + 运行记录 模型
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey, utcnow


class PipelineTemplate(Base, UUIDPrimaryKey, TimestampMixin):
    """流程模板"""
    __tablename__ = "pipeline_templates"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(64), default="CodeOutlined")
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="custom",
        comment="dev | ops | review | data | custom",
    )
    tags: Mapped[str] = mapped_column(String(512), default="")
    steps_json: Mapped[list] = mapped_column(JSON, default=list, comment="PipelineStep[]")
    avg_duration: Mapped[int] = mapped_column(Integer, default=0, comment="ms")
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)


class PipelineRun(Base, UUIDPrimaryKey):
    """流程运行记录"""
    __tablename__ = "pipeline_runs"

    template_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("pipeline_templates.id"), nullable=True,
    )
    template_name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(
        String(32), default="running",
        comment="running | completed | failed | paused",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    duration: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    completed_steps: Mapped[int] = mapped_column(Integer, default=0)
    failed_steps: Mapped[int] = mapped_column(Integer, default=0)
    triggered_by: Mapped[str] = mapped_column(String(64), default="手动触发")
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow,
    )
