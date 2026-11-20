"""
Router — 动态能力路由

根据 capability 将任务路由到最合适的 Worker。
策略: least-loaded（优先选择负载最小的可用 Worker）。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from app.runtime.scheduler.models import Capability, WorkerInfo
from app.runtime.scheduler.worker_pool import WorkerPool


class Router:
    """基于能力的动态路由器"""

    def __init__(self, worker_pool: WorkerPool):
        self.pool = worker_pool

    async def route(self, capability: Capability) -> Optional[WorkerInfo]:
        """为 capability 找到最合适的 Worker（least-loaded 策略）"""
        candidates = await self.pool.get_by_capability(capability)
        if not candidates:
            # 尝试模糊匹配？未来可扩展
            return None
        # least-loaded: 选 current_load 最小的
        candidates.sort(key=lambda w: (w.current_load, w.last_heartbeat))
        return candidates[0]

    async def route_to_specific(self, capability: Capability, worker_id: str) -> Optional[WorkerInfo]:
        """路由到指定 Worker（需要匹配 capability）"""
        worker = await self.pool.get(worker_id)
        if worker and capability in worker.capabilities and worker.is_available and worker.is_healthy:
            return worker
        return None

    async def route_any(self) -> Optional[WorkerInfo]:
        """路由到任意可用 Worker"""
        candidates = await self.pool.list_available()
        if not candidates:
            return None
        candidates.sort(key=lambda w: w.current_load)
        return candidates[0]

    async def capabilities(self) -> set[Capability]:
        """返回当前可调度的所有能力"""
        available = await self.pool.list_available()
        caps: set[Capability] = set()
        for w in available:
            caps.update(w.capabilities)
        return caps
