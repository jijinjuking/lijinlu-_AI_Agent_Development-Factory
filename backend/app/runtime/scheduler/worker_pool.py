"""
Worker Pool — Worker 注册 + 健康追踪

管理所有 Worker 的生命周期：
- register / deregister
- capability 索引
- 心跳检测 + 健康检查
- 负载追踪
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from app.runtime.scheduler.models import WorkerInfo, Capability


class WorkerPool:
    """Worker 注册与管理池"""

    def __init__(self, heartbeat_timeout: float = 30.0):
        self._workers: dict[str, WorkerInfo] = {}
        self._by_capability: dict[Capability, list[str]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self.heartbeat_timeout = heartbeat_timeout

    # ---- 注册 / 注销 ----

    async def register(self, worker: WorkerInfo) -> None:
        """注册 Worker"""
        async with self._lock:
            self._workers[worker.worker_id] = worker
            for cap in worker.capabilities:
                if worker.worker_id not in self._by_capability[cap]:
                    self._by_capability[cap].append(worker.worker_id)

    async def deregister(self, worker_id: str) -> bool:
        """注销 Worker"""
        async with self._lock:
            worker = self._workers.pop(worker_id, None)
            if worker:
                for cap in worker.capabilities:
                    self._by_capability[cap] = [
                        wid for wid in self._by_capability[cap] if wid != worker_id
                    ]
                return True
            return False

    # ---- 心跳 ----

    async def heartbeat(self, worker_id: str) -> bool:
        """更新 Worker 心跳时间"""
        async with self._lock:
            worker = self._workers.get(worker_id)
            if worker:
                worker.last_heartbeat = datetime.now(timezone.utc)
                if worker.status == "unhealthy":
                    worker.status = "idle"
                return True
            return False

    # ---- 健康检查 ----

    async def check_health(self) -> list[str]:
        """返回不健康的 Worker ID 列表"""
        now = datetime.now(timezone.utc)
        unhealthy: list[str] = []
        async with self._lock:
            for wid, worker in self._workers.items():
                elapsed = (now - worker.last_heartbeat).total_seconds()
                if elapsed > self.heartbeat_timeout:
                    worker.status = "unhealthy"
                    unhealthy.append(wid)
        return unhealthy

    async def purge_unhealthy(self) -> list[str]:
        """移除并返回所有不健康的 Worker"""
        unhealthy = await self.check_health()
        for wid in unhealthy:
            await self.deregister(wid)
        return unhealthy

    # ---- 查询 ----

    async def get(self, worker_id: str) -> Optional[WorkerInfo]:
        return self._workers.get(worker_id)

    async def get_by_capability(self, capability: Capability) -> list[WorkerInfo]:
        """获取具备某能力的可用 Worker"""
        async with self._lock:
            worker_ids = self._by_capability.get(capability, [])
            return [
                w for w in (self._workers.get(wid) for wid in worker_ids)
                if w and w.is_available and w.is_healthy
            ]

    async def list_available(self) -> list[WorkerInfo]:
        """列出所有可用的 Worker"""
        async with self._lock:
            return [w for w in self._workers.values() if w.is_available and w.is_healthy]

    async def list_all(self) -> list[WorkerInfo]:
        """列出所有 Worker（含不健康的）"""
        async with self._lock:
            return list(self._workers.values())

    @property
    async def size(self) -> int:
        async with self._lock:
            return len(self._workers)

    # ---- 负载管理 ----

    async def acquire(self, worker_id: str) -> bool:
        """给 Worker 增加负载计数"""
        async with self._lock:
            worker = self._workers.get(worker_id)
            if worker and worker.is_available:
                worker.current_load += 1
                if worker.current_load >= worker.max_concurrency:
                    worker.status = "busy"
                return True
            return False

    async def release(self, worker_id: str) -> None:
        """减少 Worker 的负载计数"""
        async with self._lock:
            worker = self._workers.get(worker_id)
            if worker:
                worker.current_load = max(0, worker.current_load - 1)
                if worker.status == "busy" and worker.current_load < worker.max_concurrency:
                    worker.status = "idle"
