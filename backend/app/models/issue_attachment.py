"""
AI Runtime OS — IssueAttachment 模型
Issue 附件，存储用户上传的开发文档（PRD、架构设计等）
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class IssueAttachment(Base, UUIDPrimaryKey, TimestampMixin):
    """Issue 附件表"""
    __tablename__ = "issue_attachments"

    issue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content_text: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))

    # 关系
    issue: Mapped["Issue"] = relationship("Issue", back_populates="attachments")
