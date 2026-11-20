"""
State Manager — 轻量 State 管理服务
load / save / update — State 只存引用，内容走 Artifact Store。
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.runtime.state_manager.lightweight_state import LightweightState
from app.runtime.state_manager.state_validator import StateValidator, StateTooLargeError

logger = logging.getLogger("ai_runtime_os.state_manager")


class StateManager:
    """轻量 State 管理。当前适配 SQLite，生产可扩展 Redis 缓存层。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._state_cache: dict[str, LightweightState] = {}

    # ── CRUD ──

    async def load(self, task_id: str) -> LightweightState | None:
        """加载任务的 State。先查内存缓存，再查 DB。"""
        if task_id in self._state_cache:
            return self._state_cache[task_id]

        uid = uuid.UUID(task_id)
        result = await self.db.execute(select(Task).where(Task.id == uid))
        task = result.scalar_one_or_none()
        if not task or not task.state_json:
            return None

        state = LightweightState.from_dict(task.state_json)
        self._state_cache[task_id] = state
        return state

    async def save(self, task_id: str, state: LightweightState) -> None:
        """保存 State。先验证大小，再写入 DB。"""
        state_dict = state.to_dict()

        # ── 验证 ──
        StateValidator.validate(state_dict)

        uid = uuid.UUID(task_id)
        result = await self.db.execute(select(Task).where(Task.id == uid))
        task = result.scalar_one_or_none()
        if not task:
            raise ValueError(f"Task {task_id} not found")

        task.state_json = state_dict
        await self.db.commit()
        await self.db.refresh(task)

        # 更新缓存
        self._state_cache[task_id] = state
        size = StateValidator.get_size(state_dict)
        logger.debug("State saved: task=%s size=%d bytes", task_id, size)

    async def update_field(self, task_id: str, updates: dict[str, Any]) -> LightweightState:
        """部分更新 State 字段。"""
        state = await self.load(task_id)
        if state is None:
            state = LightweightState.create_for_task(task_id)

        for key, value in updates.items():
            if hasattr(state, key):
                setattr(state, key, value)

        await self.save(task_id, state)
        return state

    async def initialize(self, task_id: str, goal: str = "", project_id: str = "") -> LightweightState:
        """为新任务初始化空 State。如 Task DB 记录不存在则自动创建。"""
        state = LightweightState.create_for_task(task_id, goal, project_id)
        state_dict = state.to_dict()
        StateValidator.validate(state_dict)

        uid = uuid.UUID(task_id)
        result = await self.db.execute(select(Task).where(Task.id == uid))
        task = result.scalar_one_or_none()

        if not task:
            # 创建 Task DB 记录，填充必填字段
            task = Task(
                id=uid,
                name=f"task-{str(task_id)[:8]}",
                goal_description=goal,
                status="pending",
            )
            self.db.add(task)

        task.state_json = state_dict
        await self.db.commit()
        await self.db.refresh(task)

        self._state_cache[task_id] = state
        size = StateValidator.get_size(state_dict)
        logger.debug("State initialized: task=%s size=%d bytes", task_id, size)
        return state

    async def get_size(self, task_id: str) -> int:
        """获取 State 的字节大小。"""
        state = await self.load(task_id)
        if state is None:
            return 0
        return StateValidator.get_size(state.to_dict())

    def clear_cache(self, task_id: str | None = None) -> None:
        """清除缓存。不传参数清全部。"""
        if task_id:
            self._state_cache.pop(task_id, None)
        else:
            self._state_cache.clear()
