"""
AI Runtime OS — Memory（三层记忆）模型
"""
from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class MemoryEntry(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "memories"

    layer: Mapped[str] = mapped_column(
        String(16), nullable=False, default="project",
        comment="cloud | user | project",
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(512), default="")
    source: Mapped[str] = mapped_column(
        String(64), default="手动设置",
        comment="自动学习 | 手动设置 | 工作日志",
    )
    importance: Mapped[str] = mapped_column(
        String(16), default="medium",
        comment="high | medium | low",
    )
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
