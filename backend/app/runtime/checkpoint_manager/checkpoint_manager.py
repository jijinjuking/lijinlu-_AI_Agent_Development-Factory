"""
Checkpoint Manager — 检查点管理
每个 Workflow 节点执行完自动写 Checkpoint（持久化到 SQLite）。
支持：保存 / 加载最新 / 列表 / 清理
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskCheckpoint
from app.runtime.state_manager.lightweight_state import LightweightState
from app.runtime.state_manager.state_manager import StateManager

logger = logging.getLogger("ai_runtime_os.checkpoint_manager")


class CheckpointManager:
    """Checkpoint 持久化管理器"""

    MAX_CHECKPOINTS_PER_TASK = 20

    def __init__(self, db: AsyncSession, state_manager: StateManager | None = None):
        self.db = db
        self.state_manager = state_manager or StateManager(db)

    async def save_checkpoint(
        self,
        task_id: str,
        event_seq_num: int | None = None,
    ) -> TaskCheckpoint:
        """
        保存当前 State 为 Checkpoint。
        返回新创建的 Checkpoint 对象。
        """
        # 从 StateManager 获取当前 State
        state = await self.state_manager.load(task_id)
        if state is None:
            state = LightweightState.create_for_task(task_id)
            await self.state_manager.save(task_id, state)

        state_snapshot = state.to_dict()

        cp = TaskCheckpoint(
            id=uuid.uuid4(),
            task_id=uuid.UUID(task_id),
            state_snapshot=state_snapshot,
            event_seq_num=event_seq_num,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(cp)

        # 更新 Task 的 last_checkpoint_id
        uid = uuid.UUID(task_id)
        result = await self.db.execute(select(Task).where(Task.id == uid))
        task = result.scalar_one_or_none()
        if task:
            task.last_checkpoint_id = cp.id
            # 同时更新 state_json
            task.state_json = state_snapshot

        await self.db.commit()
        await self.db.refresh(cp)

        logger.info(
            "Checkpoint saved: task=%s checkpoint=%s node=%s size=%d bytes",
            task_id, cp.id, state_snapshot.get("current_node", "?"),
            len(str(state_snapshot)),
        )

        # ── 自动清理旧 Checkpoint ──
        await self._prune_old_checkpoints(task_id)

        return cp

    async def load_latest(self, task_id: str) -> TaskCheckpoint | None:
        """加载任务的最新 Checkpoint"""
        uid = uuid.UUID(task_id)
        result = await self.db.execute(
            select(TaskCheckpoint)
            .where(TaskCheckpoint.task_id == uid)
            .order_by(desc(TaskCheckpoint.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def load_checkpoint(self, checkpoint_id: str) -> TaskCheckpoint | None:
        """通过 Checkpoint ID 加载单个 Checkpoint（含完整 state_snapshot）"""
        uid = uuid.UUID(checkpoint_id)
        result = await self.db.execute(
            select(TaskCheckpoint).where(TaskCheckpoint.id == uid)
        )
        return result.scalar_one_or_none()
        return result.scalar_one_or_none()

    async def restore_from_checkpoint(
        self,
        task_id: str,
        checkpoint_id: str | None = None,
    ) -> LightweightState:
        """
        从 Checkpoint 恢复 State。
        不传 checkpoint_id 则恢复最新。
        """
        if checkpoint_id:
            uid = uuid.UUID(checkpoint_id)
            result = await self.db.execute(
                select(TaskCheckpoint).where(TaskCheckpoint.id == uid)
            )
            cp = result.scalar_one_or_none()
            if not cp:
                raise ValueError(f"Checkpoint {checkpoint_id} not found")
        else:
            cp = await self.load_latest(task_id)
            if not cp:
                raise ValueError(f"No checkpoint found for task {task_id}")

        state = LightweightState.from_dict(cp.state_snapshot)
        await self.state_manager.save(task_id, state)

        logger.info("State restored from checkpoint: task=%s checkpoint=%s", task_id, cp.id)
        return state

    async def list_checkpoints(self, task_id: str) -> list[dict[str, Any]]:
        """列出任务的所有 Checkpoint（按时间倒序）"""
        uid = uuid.UUID(task_id)
        result = await self.db.execute(
            select(TaskCheckpoint)
            .where(TaskCheckpoint.task_id == uid)
            .order_by(desc(TaskCheckpoint.created_at))
        )
        cps = result.scalars().all()

        return [
            {
                "id": str(cp.id),
                "task_id": str(cp.task_id),
                "created_at": cp.created_at.isoformat() if cp.created_at else None,
                "event_seq_num": cp.event_seq_num,
                "node": cp.state_snapshot.get("current_node", ""),
                "workflow_status": cp.state_snapshot.get("workflow_status", ""),
                "state_size": len(str(cp.state_snapshot)),
            }
            for cp in cps
        ]

    async def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """删除指定 Checkpoint"""
        uid = uuid.UUID(checkpoint_id)
        result = await self.db.execute(
            select(TaskCheckpoint).where(TaskCheckpoint.id == uid)
        )
        cp = result.scalar_one_or_none()
        if not cp:
            return False

        await self.db.delete(cp)
        await self.db.commit()
        return True

    async def _prune_old_checkpoints(self, task_id: str) -> int:
        """清理超过 MAX_CHECKPOINTS_PER_TASK 的旧 Checkpoint"""
        uid = uuid.UUID(task_id)
        result = await self.db.execute(
            select(TaskCheckpoint)
            .where(TaskCheckpoint.task_id == uid)
            .order_by(desc(TaskCheckpoint.created_at))
        )
        all_cps = result.scalars().all()

        if len(all_cps) <= self.MAX_CHECKPOINTS_PER_TASK:
            return 0

        to_delete = all_cps[self.MAX_CHECKPOINTS_PER_TASK:]
        for cp in to_delete:
            await self.db.delete(cp)
        await self.db.commit()

        logger.debug("Pruned %d old checkpoints for task %s", len(to_delete), task_id)
        return len(to_delete)
