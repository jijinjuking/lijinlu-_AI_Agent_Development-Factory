"""W31-32 Runtime Federation — 联邦网关

跨集群任务分发的核心路由层：选择目标 → 创建跨集群任务 → 跟踪状态。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Callable
from uuid import uuid4

from .models import (
    CrossClusterTask,
    DispatchPolicy,
    DispatchRequest,
    DispatchResult,
    FederationMember,
    FederationPolicyConfig,
    MemberStatus,
)
from .policy import FederationPolicyEngine
from .registry import FederationRegistry

logger = logging.getLogger(__name__)

# 默认分发超时（秒）
DEFAULT_DISPATCH_TIMEOUT = 60
# 后台监控间隔
MONITOR_INTERVAL = 5


class FederationGateway:
    """联邦网关 — 跨集群任务的统一入口"""

    def __init__(self, registry: FederationRegistry,
                 policy_engine: FederationPolicyEngine | None = None):
        self._registry = registry
        self._policy = policy_engine or FederationPolicyEngine()
        self._tasks: dict[str, CrossClusterTask] = {}
        self._dispatchers: dict[str, Callable] = {}  # capability → dispatcher callable
        self._monitor_task: asyncio.Task | None = None
        self._completion_events: dict[str, asyncio.Event] = {}

    # ── 分发 ──────────────────────────────────

    async def dispatch(self, request: DispatchRequest,
                       source_member_id: str = "",
                       source_cluster_id: str = "") -> DispatchResult:
        """分发任务到联邦中的目标成员"""
        # 获取候选成员
        candidates = self._registry.get_available_members(
            capability=request.capability)

        # 排除源成员（如果指定）
        if source_member_id:
            candidates = [m for m in candidates if m.member_id != source_member_id]

        if not candidates:
            return DispatchResult(
                accepted=False,
                reason="No available members with required capability",
            )

        # 选择策略
        policy = request.policy or self._policy.get_config().dispatch

        # 获取源成员信息用于策略决策
        source_member = self._registry.get_member(source_member_id)
        prefer_region = source_member.region if source_member else ""

        target = self._policy.select_target(
            candidates, policy=policy, prefer_region=prefer_region)

        if not target:
            return DispatchResult(
                accepted=False,
                policy_used=policy,
                reason="No suitable target found",
            )

        # 创建跨集群任务
        task = CrossClusterTask(
            source_cluster_id=source_cluster_id,
            target_cluster_id=target.cluster_id,
            target_member_id=target.member_id,
            capability=request.capability,
            payload=request.payload,
            priority=request.priority,
            requires_state_sync=request.requires_state_sync,
            requires_artifact_sync=request.requires_artifact_sync,
            artifact_ids=request.artifact_ids,
            status="dispatched",
            dispatched_at=datetime.now(),
        )

        self._tasks[task.task_id] = task

        # 更新目标成员负载
        target.used_capacity += 1
        target.active_tasks += 1

        # 如果有注册的 dispatcher，异步执行
        dispatcher = self._dispatchers.get(request.capability)
        if dispatcher:
            asyncio.ensure_future(self._execute_remote(task, dispatcher))

        logger.info("Task %s dispatched to %s (policy=%s)",
                     task.task_id, target.name, policy.value)

        return DispatchResult(
            task_id=task.task_id,
            accepted=True,
            target_cluster_id=target.cluster_id,
            target_member_id=target.member_id,
            policy_used=policy,
            reason=f"Dispatched to {target.name} ({target.region}/{target.zone})",
        )

    async def dispatch_batch(self, requests: list[DispatchRequest],
                             source_member_id: str = "",
                             source_cluster_id: str = "") -> list[DispatchResult]:
        """批量分发任务"""
        results = []
        for req in requests:
            result = await self.dispatch(req, source_member_id, source_cluster_id)
            results.append(result)
        return results

    # ── 任务管理 ──────────────────────────────

    def get_task(self, task_id: str) -> CrossClusterTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self, status: str = "",
                   target_cluster_id: str = "",
                   target_member_id: str = "") -> list[CrossClusterTask]:
        """列出跨集群任务，支持多维度过滤"""
        result = list(self._tasks.values())
        if status:
            result = [t for t in result if t.status == status]
        if target_cluster_id:
            result = [t for t in result if t.target_cluster_id == target_cluster_id]
        if target_member_id:
            result = [t for t in result if t.target_member_id == target_member_id]
        return result

    async def cancel_task(self, task_id: str) -> bool:
        """取消跨集群任务"""
        task = self._tasks.get(task_id)
        if not task or task.status in ("completed", "failed", "cancelled"):
            return False

        task.status = "cancelled"
        task.completed_at = datetime.now()

        # 释放目标成员容量
        target = self._registry.get_member(task.target_member_id)
        if target:
            target.used_capacity = max(0, target.used_capacity - 1)
            target.active_tasks = max(0, target.active_tasks - 1)

        logger.info("Task %s cancelled", task_id)
        return True

    async def complete_task(self, task_id: str, success: bool = True,
                            result: dict | None = None,
                            error_message: str = "") -> CrossClusterTask | None:
        """标记跨集群任务完成"""
        task = self._tasks.get(task_id)
        if not task:
            return None

        task.status = "completed" if success else "failed"
        task.completed_at = datetime.now()
        if result:
            task.result = result
        task.error_message = error_message

        # 释放目标成员容量
        target = self._registry.get_member(task.target_member_id)
        if target:
            target.used_capacity = max(0, target.used_capacity - 1)
            target.active_tasks = max(0, target.active_tasks - 1)
            if success:
                target.total_tasks_completed += 1

        # 触发等待者
        event = self._completion_events.pop(task_id, None)
        if event:
            event.set()

        logger.info("Task %s %s", task_id, task.status)
        return task

    async def wait_for_task(self, task_id: str,
                            timeout: float = DEFAULT_DISPATCH_TIMEOUT) -> CrossClusterTask | None:
        """等待跨集群任务完成"""
        task = self._tasks.get(task_id)
        if not task:
            return None

        # 已经完成
        if task.status in ("completed", "failed", "cancelled"):
            return task

        event = asyncio.Event()
        self._completion_events[task_id] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self._completion_events.pop(task_id, None)
            return self._tasks.get(task_id)
        return self._tasks.get(task_id)

    # ── Dispatcher 注册 ──────────────────────

    def register_dispatcher(self, capability: str, dispatcher: Callable):
        """注册能力分发器"""
        self._dispatchers[capability] = dispatcher
        logger.info("Registered dispatcher for capability: %s", capability)

    def unregister_dispatcher(self, capability: str):
        """注销能力分发器"""
        self._dispatchers.pop(capability, None)

    async def _execute_remote(self, task: CrossClusterTask, dispatcher: Callable):
        """异步执行远程任务"""
        try:
            task.status = "running"
            task.started_at = datetime.now()
            result = await dispatcher(task.payload)
            await self.complete_task(task.task_id, success=True, result=result)
        except Exception as e:
            logger.exception("Remote task %s failed", task.task_id)
            await self.complete_task(
                task.task_id, success=False,
                error_message=str(e))

    # ── 统计 ──────────────────────────────────

    def get_stats(self) -> dict:
        """获取网关统计"""
        tasks = list(self._tasks.values())
        return {
            "total_tasks": len(tasks),
            "pending": sum(1 for t in tasks if t.status == "pending"),
            "dispatched": sum(1 for t in tasks if t.status == "dispatched"),
            "running": sum(1 for t in tasks if t.status == "running"),
            "completed": sum(1 for t in tasks if t.status == "completed"),
            "failed": sum(1 for t in tasks if t.status == "failed"),
            "cancelled": sum(1 for t in tasks if t.status == "cancelled"),
            "registered_dispatchers": list(self._dispatchers.keys()),
        }

    # ── 后台监控 ──────────────────────────────

    async def _monitor_loop(self):
        """后台监控循环 — 检测超时任务"""
        timeout = self._policy.get_config().dispatch_timeout_seconds
        while True:
            try:
                now = datetime.now()
                for task in list(self._tasks.values()):
                    if task.status in ("dispatched", "running") and task.dispatched_at:
                        elapsed = (now - task.dispatched_at).total_seconds()
                        if elapsed > timeout:
                            task.retry_count += 1
                            max_retry = self._policy.get_config().max_retry_cross_cluster
                            if task.retry_count > max_retry:
                                await self.complete_task(
                                    task.task_id, success=False,
                                    error_message=f"Timeout after {max_retry} retries")
                                logger.warning("Task %s failed: max retries exceeded", task.task_id)
                            else:
                                logger.warning("Task %s timeout, retry %d/%d",
                                               task.task_id, task.retry_count, max_retry)
            except Exception:
                logger.exception("Error in federation monitor loop")
            await asyncio.sleep(MONITOR_INTERVAL)

    def start_monitor(self):
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.ensure_future(self._monitor_loop())

    async def stop_monitor(self):
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
