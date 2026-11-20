"""
AI Runtime OS — Artifact 产物模型
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.models.base import Base, utcnow


class Artifact(Base):
    """产物（State 只存引用，内容存文件系统）"""
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tasks.id"), nullable=True)
    artifact_type: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="requirement_doc | architecture_doc | code_file | test_result | ...",
    )
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_artifact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_agent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow,
    )
