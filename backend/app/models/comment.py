"""
AI Runtime OS — Comment 模型
Issue 评论，支持线程回复
"""
from __future__ import annotations

import uuid

from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKey, TimestampMixin


class Comment(Base, UUIDPrimaryKey, TimestampMixin):
    """Issue 评论"""
    __tablename__ = "comments"

    issue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(128), default="system")

    # 可选：回复某条评论
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comments.id", ondelete="SET NULL"), nullable=True,
    )

    # 关系
    issue: Mapped["Issue"] = relationship(
        foreign_keys=[issue_id], back_populates="comments",
    )
    parent: Mapped["Comment | None"] = relationship(
        foreign_keys=[parent_id], remote_side="Comment.id",
    )
