"""
优先级任务队列 — heapq 实现

- enqueue: 按 priority 入队（数值越小优先级越高）
- dequeue: 按优先级出队，同优先级 FIFO
- peek: 查看队首
- status 查询 + 取消
"""
from __future__ import annotations

import asyncio
import heapq
import itertools
from typing import Optional

from app.runtime.scheduler.models import ScheduledTask, TaskStatus


class TaskQueue:
    """线程不安全但协程安全的优先级任务队列"""

    def __init__(self):
        self._heap: list[tuple[int, int, ScheduledTask]] = []  # (priority, seq, task)
        self._counter = itertools.count()
        self._tasks: dict[str, ScheduledTask] = {}  # task_id → task (快速查找)
        self._lock = asyncio.Lock()

    # ---- 入队 ----

    async def enqueue(self, task: ScheduledTask) -> None:
        """按 priority 入队"""
        async with self._lock:
            task.status = TaskStatus.QUEUED
            seq = next(self._counter)
            heapq.heappush(self._heap, (task.priority, seq, task))
            self._tasks[task.task_id] = task

    async def enqueue_batch(self, tasks: list[ScheduledTask]) -> None:
        """批量入队"""
        for task in tasks:
            await self.enqueue(task)

    # ---- 出队 ----

    async def dequeue(self) -> Optional[ScheduledTask]:
        """取出优先级最高的任务"""
        async with self._lock:
            while self._heap:
                _, _, task = heapq.heappop(self._heap)
                if task.status == TaskStatus.QUEUED:
                    return task
                # 已取消/已完成的任务跳过
            return None

    # ---- 偷看 ----

    async def peek(self) -> Optional[ScheduledTask]:
        """查看队首但不取出"""
        async with self._lock:
            while self._heap:
                _, _, task = self._heap[0]
                if task.status == TaskStatus.QUEUED:
                    return task
                heapq.heappop(self._heap)
            return None

    # ---- 移除 ----

    async def cancel(self, task_id: str) -> bool:
        """取消任务（标记为 CANCELLED）"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task and task.status in (TaskStatus.QUEUED, TaskStatus.RETRYING):
                task.status = TaskStatus.CANCELLED
                return True
            return False

    async def remove(self, task_id: str) -> Optional[ScheduledTask]:
        """从队列中移除并返回任务"""
        async with self._lock:
            task = self._tasks.pop(task_id, None)
            return task

    # ---- 查询 ----

    async def get(self, task_id: str) -> Optional[ScheduledTask]:
        return self._tasks.get(task_id)

    async def status(self, task_id: str) -> Optional[TaskStatus]:
        task = self._tasks.get(task_id)
        return task.status if task else None

    @property
    async def size(self) -> int:
        async with self._lock:
            return sum(1 for t in self._tasks.values() if t.status == TaskStatus.QUEUED)

    @property
    async def total(self) -> int:
        async with self._lock:
            return len(self._tasks)

    async def pending(self) -> list[ScheduledTask]:
        """返回所有等待中的任务（按优先级排序）"""
        async with self._lock:
            pending = [t for t in self._tasks.values() if t.status == TaskStatus.QUEUED]
            pending.sort(key=lambda t: t.priority)
            return pending

    async def clear(self) -> None:
        """清空队列"""
        async with self._lock:
            self._heap.clear()
            self._tasks.clear()
