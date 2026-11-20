"""
AI Runtime OS — Project 模型
议题的容器，一个项目包含多个 Issue
"""
from __future__ import annotations

import uuid

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class Project(Base, UUIDPrimaryKey, TimestampMixin):
    """项目——Issue 的容器"""
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        String(32), default="active",
        comment="active | archived",
    )
    created_by: Mapped[str] = mapped_column(String(128), default="")
