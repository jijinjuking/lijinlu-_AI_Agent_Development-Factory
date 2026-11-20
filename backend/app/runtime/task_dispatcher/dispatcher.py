"""
Task Dispatcher — 任务分发器

将调度结果分发到具体 Worker/Agent 执行。
"""

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from app.runtime.scheduler import ScheduleResult, TaskStatus

logger = logging.getLogger(__name__)


class TaskDispatcher:
    """
    任务分发器。

    将 ScheduleResult 分发到具体 Worker/Agent 执行，
    管理执行生命周期。
    """

    def __init__(self, worker_manager=None, sandbox_manager=None):
        self._workers = worker_manager
        self._sandbox = sandbox_manager
        self._active_dispatches: Dict[str, asyncio.Task] = {}
        self._dispatch_handlers: Dict[str, List[Callable]] = {}
        self._results: Dict[str, List[dict]] = {}

    def register_handler(self, event_type: str, handler: Callable) -> None:
        """注册分发事件处理器"""
        self._dispatch_handlers.setdefault(event_type, []).append(handler)

    async def dispatch(self, result: ScheduleResult) -> bool:
        """
        分发任务到 Worker。

        返回 True 表示分发成功。
        """
        task_id = result.task_id
        worker_id = result.worker_id

        # 记录分发事件
        self._record_result(task_id, {
            "event": "dispatched",
            "worker_id": worker_id,
            "model": result.model_name,
            "timestamp": time.time(),
        })

        # 通知 Worker（如果有 Worker Manager）
        if self._workers:
            worker = self._workers.get(worker_id)
            if worker:
                self._workers.update_status(worker_id, "busy")
                self._workers.update_load(worker_id, worker.current_load + 1)

        # 触发处理器
        await self._trigger_handlers("task_dispatched", {
            "task_id": task_id,
            "worker_id": worker_id,
            "model": result.model_name,
        })

        logger.info(f"Task {task_id} dispatched to worker {worker_id}")
        return True

    async def complete(self, task_id: str) -> None:
        """标记任务完成"""
        self._record_result(task_id, {
            "event": "completed",
            "timestamp": time.time(),
        })
        await self._trigger_handlers("task_completed", {"task_id": task_id})

    async def fail(self, task_id: str, error: str) -> None:
        """标记任务失败"""
        self._record_result(task_id, {
            "event": "failed",
            "error": error,
            "timestamp": time.time(),
        })
        await self._trigger_handlers("task_failed", {
            "task_id": task_id,
            "error": error,
        })

    def cancel(self, task_id: str) -> bool:
        """取消分发"""
        dispatch_task = self._active_dispatches.pop(task_id, None)
        if dispatch_task and not dispatch_task.done():
            dispatch_task.cancel()
            return True
        return False

    def get_results(self, task_id: str) -> List[dict]:
        """获取任务分发记录"""
        return self._results.get(task_id, [])

    # ---- Internal ----

    def _record_result(self, task_id: str, entry: dict) -> None:
        self._results.setdefault(task_id, []).append(entry)

    async def _trigger_handlers(self, event_type: str, data: dict) -> None:
        handlers = self._dispatch_handlers.get(event_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.error(f"Dispatch handler failed: {e}")
