"""
AI Runtime OS — Issue 模型
用户提出的需求/议题，由架构师 Agent 分解后派发为子任务
"""
from __future__ import annotations

import uuid

from datetime import datetime

from sqlalchemy import DateTime, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey, utcnow


class Issue(Base, UUIDPrimaryKey, TimestampMixin):
    """议题——用户需求入口，分解后生成子任务树"""
    __tablename__ = "issues"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False,
    )

    # 基本信息
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")

    # 状态机：open → in_progress → pending_review → resolved / closed
    status: Mapped[str] = mapped_column(
        String(32), default="open",
        comment="open | in_progress | pending_review | resolved | closed",
    )
    priority: Mapped[str] = mapped_column(
        String(16), default="medium",
        comment="critical | high | medium | low",
    )

    # 提交人 & 分配到的架构师 Agent
    created_by: Mapped[str] = mapped_column(String(128), default="")
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True,
    )

    # 分解结果
    decomposition_strategy: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="template_match | llm_generate | hybrid | query_expansion",
    )
    task_tree_json: Mapped[dict | None] = mapped_column(Text, nullable=True)
    # task_tree_json 结构：
    # {
    #   "version": 1,
    #   "root_task_id": "<uuid>",
    #   "nodes": [{"id": "...", "parent_id": null, "title": "...", "role": "..."}],
    #   "edges": [{"from": "...", "to": "..."}],
    #   "decomposed_at": "2026-06-05T10:00:00Z",
    #   "strategy": "hybrid",
    # }

    # 时间戳
    decomposed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # 关系
    project: Mapped["Project"] = relationship(
        foreign_keys=[project_id],
    )
    assigned_agent: Mapped["Agent | None"] = relationship(
        foreign_keys=[assigned_agent_id],
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="issue",
        foreign_keys="[Task.issue_id]",
    )
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="issue",
        foreign_keys="[Comment.issue_id]",
    )

    # 附件
    attachments: Mapped[list["IssueAttachment"]] = relationship(
        back_populates="issue",
        cascade="all, delete-orphan",
    )
