"""
AI Runtime OS — Task + Checkpoint 模型
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, Float, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey, utcnow


class Task(Base, UUIDPrimaryKey, TimestampMixin):
    """Runtime Kernel 核心任务"""
    __tablename__ = "tasks"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    goal_description: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(String(255), default="")

    # 状态机：pending → running → paused → completed / failed / cancelled
    status: Mapped[str] = mapped_column(String(32), default="pending")

    # Kanban 看板列
    kanban_column: Mapped[str] = mapped_column(
        String(32), default="todo",
        comment="todo | in_progress | review | done | failed",
    )

    # 关联
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("agents.id"), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(128), default="")

    # 议题 & 父子任务
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("issues.id", ondelete="SET NULL"), nullable=True,
    )
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True,
    )

    # 优先级：1~10，10 最高
    priority: Mapped[str] = mapped_column(
        String(16), default="medium",
        comment="critical | high | medium | low",
    )
    priority_level: Mapped[int] = mapped_column(Integer, default=5)

    # 轻量 State（只存引用）
    state_json: Mapped[dict] = mapped_column(JSON, default=dict)
    workflow_graph_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 时间戳
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 耗时（ms）
    duration: Mapped[int] = mapped_column(Integer, default=0)

    # 成本统计
    token_usage: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)

    # Tags
    tags: Mapped[str] = mapped_column(String(512), default="", comment="逗号分隔")

    assigned_worker: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("task_checkpoints.id"), nullable=True,
    )

    checkpoints: Mapped[list["TaskCheckpoint"]] = relationship(
        back_populates="task",
        foreign_keys="[TaskCheckpoint.task_id]",
    )

    # 议题 & 父子任务关系
    issue: Mapped["Issue | None"] = relationship(
        back_populates="tasks",
        foreign_keys=[issue_id],
    )
    parent_task: Mapped["Task | None"] = relationship(
        "Task",
        remote_side="Task.id",
        back_populates="child_tasks",
        foreign_keys=[parent_task_id],
    )
    child_tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="parent_task",
    )


class TaskCheckpoint(Base, UUIDPrimaryKey):
    """故障恢复检查点"""
    __tablename__ = "task_checkpoints"

    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tasks.id"), nullable=False)
    state_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    event_seq_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow,
    )

    task: Mapped["Task"] = relationship(
        back_populates="checkpoints",
        foreign_keys=[task_id],
    )
