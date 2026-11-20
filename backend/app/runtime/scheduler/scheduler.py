"""
Scheduler — 基于 Capability 的中央任务调度器

整合:
- TaskQueue: 优先级队列
- WorkerPool: Worker 管理与能力索引
- Router: 能力路由
- RetryPolicy: 重试策略
- TimeoutPolicy: 超时控制
- LangGraphAdapter: 工作流执行
- EventBus: 事件发布

调度循环:
  submit → enqueue → dequeue → route → execute → handle result
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.event_bus import Event, event_bus
from app.core.event_types import EventType
from app.runtime.execution_engine.langgraph_adapter import LangGraphAdapter
from app.runtime.execution_engine.node_executor import NodeExecutor
from app.runtime.execution_engine.workflow_schema import WorkflowSpec, create_default_state
from app.runtime.checkpoint_manager.checkpoint_manager import CheckpointManager
from app.runtime.scheduler.models import (
    Capability,
    RetryConfig,
    ScheduleResult,
    ScheduledTask,
    TaskStatus,
    TimeoutConfig,
    WorkerInfo,
)
from app.runtime.scheduler.retry_policy import RetryPolicy
from app.runtime.scheduler.router import Router
from app.runtime.scheduler.task_queue import TaskQueue
from app.runtime.scheduler.timeout_policy import TimeoutPolicy
from app.runtime.scheduler.worker_pool import WorkerPool

logger = logging.getLogger(__name__)


class Scheduler:
    """
    Capability-based 任务调度器。

    用法:
        scheduler = Scheduler(node_executor=executor)
        await scheduler.start()
        task = ScheduledTask(
            task_id="t1",
            capability="code_generation",
            workflow_spec=spec,
            priority=3,
        )
        await scheduler.submit(task)
        # ... tasks execute automatically in background
        result = await scheduler.wait_for("t1")
        await scheduler.stop()
    """

    def __init__(
        self,
        node_executor: NodeExecutor | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        retry_config: RetryConfig | None = None,
        timeout_config: TimeoutConfig | None = None,
        policy_engine: Any | None = None,
        model_router: Any | None = None,
    ):
        # 核心组件
        self.queue = TaskQueue()
        self.worker_pool = WorkerPool()
        self.router = Router(self.worker_pool)
        self.retry_policy = RetryPolicy(retry_config)
        self.timeout_policy = TimeoutPolicy(timeout_config)

        # 可选集成
        self.policy_engine = policy_engine
        self.model_router = model_router

        # 执行引擎
        from app.runtime.execution_engine.node_executor import default_node_executor
        self._node_executor = node_executor or default_node_executor
        self._adapter = LangGraphAdapter(
            node_executor=self._node_executor,
            checkpoint_manager=checkpoint_manager,
        )

        # 运行时状态
        self._running = False
        self._loop_task: asyncio.Task | None = None
        self._results: dict[str, ScheduleResult] = {}
        self._result_events: dict[str, asyncio.Event] = {}

    # ---- 注册 Worker ----

    async def register_worker(self, worker_id: str, capabilities: list[Capability]) -> None:
        """注册一个 Worker"""
        worker = WorkerInfo(
            worker_id=worker_id,
            capabilities=capabilities,
            status="idle",
        )
        await self.worker_pool.register(worker)
        await self._emit(EventType.TASK_CREATED, "", {
            "action": "worker_registered",
            "worker_id": worker_id,
            "capabilities": capabilities,
        }, "scheduler")

    async def deregister_worker(self, worker_id: str) -> None:
        """注销 Worker"""
        await self.worker_pool.deregister(worker_id)

    async def worker_heartbeat(self, worker_id: str) -> None:
        """Worker 心跳"""
        await self.worker_pool.heartbeat(worker_id)

    # ---- 提交任务 ----

    async def submit(self, task: ScheduledTask) -> str:
        """提交任务到调度队列"""
        if not task.task_id:
            task.task_id = str(uuid.uuid4())
        task.status = TaskStatus.QUEUED
        task.dispatched_at = datetime.now(timezone.utc)

        await self.queue.enqueue(task)
        await self._emit(EventType.TASK_CREATED, task.task_id, {
            "capability": task.capability,
            "priority": task.priority,
        }, "scheduler")

        logger.info(f"Task {task.task_id} queued (capability={task.capability}, priority={task.priority})")
        return task.task_id

    async def submit_spec(
        self,
        workflow_spec: WorkflowSpec,
        capability: Capability,
        priority: int = 5,
        metadata: dict | None = None,
    ) -> str:
        """快捷方法: 直接提交 WorkflowSpec"""
        task_id = str(uuid.uuid4())
        task = ScheduledTask(
            task_id=task_id,
            capability=capability,
            workflow_spec=workflow_spec,
            priority=priority,
            metadata=metadata or {},
        )
        return await self.submit(task)

    # ---- 等待结果 ----

    async def wait_for(self, task_id: str, timeout: float | None = None) -> Optional[ScheduleResult]:
        """阻塞等待任务完成（已完成的任务立即返回）"""
        # 如果结果已存在，直接返回
        if task_id in self._results:
            return self._results.pop(task_id)

        if task_id not in self._result_events:
            self._result_events[task_id] = asyncio.Event()

        try:
            await asyncio.wait_for(self._result_events[task_id].wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

        return self._results.pop(task_id, None)

    # ---- 调度循环 ----

    async def start(self) -> None:
        """启动调度循环"""
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Scheduler started")

    async def stop(self) -> None:
        """停止调度循环"""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        logger.info("Scheduler stopped")

    async def _scheduler_loop(self) -> None:
        """主调度循环"""
        while self._running:
            try:
                task = await self.queue.dequeue()
                if task is None:
                    # 无任务，短暂等待
                    await asyncio.sleep(0.1)
                    continue

                await self._dispatch(task)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")

    async def _dispatch(self, task: ScheduledTask) -> None:
        """分发单个任务: route → execute → handle result"""
        await self._emit(EventType.TASK_STARTED, task.task_id, {
            "capability": task.capability,
            "priority": task.priority,
        }, "scheduler")

        # 0. 策略引擎检查（可选）
        if self.policy_engine:
            try:
                policy_result = await self.policy_engine.check(task)
                if not policy_result.get("allowed", True):
                    logger.warning("Task %s blocked by policy: %s", task.task_id, policy_result.get("reason", "unknown"))
                    task.status = TaskStatus.CANCELLED
                    await self.queue.cancel(task.task_id)
                    return
            except Exception as e:
                logger.exception("Policy engine check failed for task %s: %s", task.task_id, e)

        # 1. 路由到 Worker（可选使用 model_router）
        worker = None
        if self.model_router:
            try:
                worker = await self.model_router.route(task.capability, task.metadata)
            except Exception as e:
                logger.exception("Model router failed for task %s: %s", task.task_id, e)
        
        if worker is None:
            worker = await self.router.route(task.capability)
        
        if worker is None:
            # 没有可用 Worker，放回队列（加延迟防止 tight loop）
            await self._emit(EventType.TASK_PAUSED, task.task_id, {
                "reason": f"no worker available for capability={task.capability}",
            }, "scheduler")
            task.status = TaskStatus.QUEUED
            await self.queue.enqueue(task)
            await asyncio.sleep(0.1)  # 避免立即重新出队
            return

        # 2. 获取 Worker 资源
        acquired = await self.worker_pool.acquire(worker.worker_id)
        if not acquired:
            task.status = TaskStatus.QUEUED
            await self.queue.enqueue(task)
            return

        task.assigned_worker_id = worker.worker_id
        task.status = TaskStatus.DISPATCHED
        await self._emit(EventType.TASK_STARTED, task.task_id, {
            "worker_id": worker.worker_id,
        }, "scheduler")

        # 3. 执行
        task.started_at = datetime.now(timezone.utc)

        try:
            result = await self._execute_with_retry(task)
        finally:
            await self.worker_pool.release(worker.worker_id)

        # 4. 记录结果
        task.completed_at = datetime.now(timezone.utc)
        self._results[task.task_id] = result

        # 5. 通知等待者
        if task.task_id in self._result_events:
            self._result_events[task.task_id].set()

        # 6. 终态事件
        if result.status == TaskStatus.COMPLETED:
            await self._emit(EventType.TASK_COMPLETED, task.task_id, {
                "duration": result.duration,
                "worker_id": worker.worker_id,
            }, "scheduler")
        else:
            await self._emit(EventType.TASK_FAILED, task.task_id, {
                "error": result.error,
                "retry_count": result.retry_count,
                "worker_id": worker.worker_id,
            }, "scheduler")

    async def _execute_with_retry(self, task: ScheduledTask) -> ScheduleResult:
        """执行任务，带重试"""
        start = datetime.now(timezone.utc)
        attempt = 0

        while True:
            attempt += 1
            task.status = TaskStatus.RUNNING if attempt == 1 else TaskStatus.RETRYING

            # 带超时执行
            result_or_none, timed_out, error = await self.timeout_policy.with_timeout(
                self._execute_workflow,
                task.capability,
                task,
            )

            duration = (datetime.now(timezone.utc) - start).total_seconds()

            if timed_out:
                error_msg = f"timeout after {self.timeout_policy.timeout_seconds(task.capability)}s"
                if self.timeout_policy.timeout_action == "retry" and self.retry_policy.should_retry("timeout", attempt):
                    await self.retry_policy.backoff(attempt, "timeout")
                    task.retry_count = attempt
                    continue
                task.status = TaskStatus.TIMED_OUT
                return ScheduleResult(
                    task_id=task.task_id,
                    status=TaskStatus.TIMED_OUT,
                    worker_id=task.assigned_worker_id,
                    error=error_msg,
                    duration=duration,
                    retry_count=task.retry_count,
                )

            if error is not None:
                error_str = str(error)
                if self.retry_policy.should_retry(error_str, attempt):
                    await self.retry_policy.backoff(attempt, error_str)
                    task.retry_count = attempt
                    continue
                task.status = TaskStatus.FAILED
                return ScheduleResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    worker_id=task.assigned_worker_id,
                    error=error_str,
                    duration=duration,
                    retry_count=task.retry_count,
                )

            # 成功
            task.status = TaskStatus.COMPLETED
            return ScheduleResult(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                worker_id=task.assigned_worker_id,
                output=result_or_none or {},
                duration=duration,
                retry_count=task.retry_count,
            )

    async def _execute_workflow(self, task: ScheduledTask) -> dict:
        """执行 LangGraph workflow"""
        graph = self._adapter.build(task.workflow_spec)
        state = create_default_state(task_id=task.task_id)

        events = []
        async for evt in self._adapter.astream(graph, state, task.task_id):
            events.append(evt)

        # 从最终事件提取 state
        final_state = events[-1].get("state", {}) if events else {}
        return final_state

    # ---- 事件发布 ----

    async def _emit(
        self,
        event_type: EventType,
        task_id: str,
        payload: dict,
        produced_by: str = "scheduler",
    ) -> None:
        """发布事件到 EventBus"""
        try:
            await event_bus.publish(Event(
                type=event_type,
                task_id=task_id,
                payload=payload,
                produced_by=produced_by,
            ))
        except Exception as e:
            logger.debug("Event publish failed (non-critical): %s", e)  # 事件发布失败不影响调度

    # ---- 查询 ----

    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        return await self.queue.cancel(task_id)

    async def task_status(self, task_id: str) -> Optional[TaskStatus]:
        return await self.queue.status(task_id)

    async def get_result(self, task_id: str) -> Optional[ScheduleResult]:
        return self._results.get(task_id)

    @property
    async def queue_size(self) -> int:
        return await self.queue.size

    @property
    async def worker_count(self) -> int:
        return await self.worker_pool.size

    async def stats(self) -> dict[str, Any]:
        """调度器统计信息"""
        return {
            "queue_size": await self.queue.size,
            "queue_total": await self.queue.total,
            "worker_count": await self.worker_pool.size,
            "available_workers": len(await self.worker_pool.list_available()),
            "capabilities": list(await self.router.capabilities()),
            "running": self._running,
        }


# 全局默认调度器
default_scheduler = Scheduler()
