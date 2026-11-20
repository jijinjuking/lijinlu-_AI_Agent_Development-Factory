"""
AI Runtime OS — Event + LLMCall 模型（Event Store + 成本追踪）
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.models.base import Base, utcnow


class Event(Base):
    """事件存储（支持 Replay）"""
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tasks.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    produced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow,
    )
    produced_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class LLMCall(Base):
    """LLM 调用记录（成本追踪核心）"""
    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tasks.id"), nullable=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("agents.id"), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(128), default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), default="")

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow,
    )
