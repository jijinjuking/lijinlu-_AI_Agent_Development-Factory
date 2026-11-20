"""
AI Runtime OS — Context Index（上下文索引）模型
存储向量索引的元数据和持久化状态
"""
from __future__ import annotations

from sqlalchemy import Integer, String, Text, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class ContextIndex(Base, UUIDPrimaryKey, TimestampMixin):
    """上下文索引条目 — 记录哪些 Memory/文档已索引到向量存储"""
    __tablename__ = "context_index"

    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="memory",
        comment="memory | document | codebase | artifact",
    )
    source_id: Mapped[str] = mapped_column(
        String(128), nullable=True,
        comment="关联源 ID（如 memory_entry.uuid）",
    )
    title: Mapped[str] = mapped_column(String(255), default="")
    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="内容 SHA256 hash，用于检测变更",
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    vector_ids: Mapped[str] = mapped_column(
        Text, default="",
        comment="逗号分隔的向量存储 ID 列表",
    )
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(16), default="active",
        comment="active | outdated | deleted",
    )
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
