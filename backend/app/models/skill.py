"""
AI Runtime OS — Skill 模型
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class Skill(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="code",
        comment="code | data | ops | communication | security | media",
    )
    icon: Mapped[str] = mapped_column(String(64), default="CodeOutlined")
    author: Mapped[str] = mapped_column(String(128), default="")
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    downloads: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[float] = mapped_column(Float, default=0.0)
    installed: Mapped[bool] = mapped_column(Boolean, default=False)
    size: Mapped[str] = mapped_column(String(32), default="0 MB")
    tags: Mapped[str] = mapped_column(String(512), default="")
    requires_config: Mapped[bool] = mapped_column(Boolean, default=False)
    config_fields: Mapped[str] = mapped_column(String(512), default="", comment="逗号分隔")
