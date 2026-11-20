"""
AI Runtime OS — User 模型
支持多租户（tenant_id 外键 → tenants 表）
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class User(Base, TimestampMixin, UUIDPrimaryKey):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")  # admin | member | viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # 多租户关联（字符串，Runtime 层管理，ORM 层不做 FK 约束）
    tenant_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )

    # 刷新令牌哈希（存储 bcrypt hash，非明文）
    refresh_token_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("idx_user_tenant", "tenant_id"),
    )

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"
