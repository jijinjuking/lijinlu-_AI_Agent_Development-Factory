"""
Heartbeat Monitor — 心跳监控器

定期检查 Worker 心跳，标记不健康 Worker。
"""

import asyncio
import logging
import time
from typing import Callable, List, Optional

from .models import WorkerInfo, WorkerStatus
from .worker_registry import WorkerRegistry

logger = logging.getLogger(__name__)


class HeartbeatMonitor:
    """心跳监控器"""

    def __init__(self, registry: WorkerRegistry, timeout_seconds: float = 30.0,
                 check_interval: float = 5.0):
        self.registry = registry
        self.timeout = timeout_seconds
        self.interval = check_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._on_unhealthy: List[Callable] = []

    def on_worker_unhealthy(self, callback: Callable) -> None:
        """注册 Worker 不健康回调"""
        self._on_unhealthy.append(callback)

    async def start(self) -> None:
        """启动心跳监控"""
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("HeartbeatMonitor started")

    async def stop(self) -> None:
        """停止心跳监控"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("HeartbeatMonitor stopped")

    async def _monitor_loop(self) -> None:
        """监控循环"""
        while self._running:
            try:
                await self._check_all()
            except Exception as e:
                logger.error(f"Heartbeat check failed: {e}")
            await asyncio.sleep(self.interval)

    async def _check_all(self) -> List[WorkerInfo]:
        """检查所有 Worker 心跳"""
        unhealthy = []
        now = time.time()

        for worker in self.registry.list_all():
            if worker.status in (WorkerStatus.OFFLINE, WorkerStatus.DRAINING):
                continue

            elapsed = now - worker.heartbeat_at
            if elapsed > self.timeout:
                worker.status = WorkerStatus.UNHEALTHY
                unhealthy.append(worker)
                logger.warning(
                    f"Worker {worker.worker_id} unhealthy: "
                    f"last heartbeat {elapsed:.0f}s ago"
                )
                for cb in self._on_unhealthy:
                    try:
                        if asyncio.iscoroutinefunction(cb):
                            await cb(worker)
                        else:
                            cb(worker)
                    except Exception as e:
                        logger.error(f"Unhealthy callback failed: {e}")

        return unhealthy

    async def purge_unhealthy(self) -> int:
        """清理不健康 Worker"""
        purged = 0
        for worker in list(self.registry.list_all()):
            if worker.status == WorkerStatus.UNHEALTHY:
                elapsed = time.time() - worker.heartbeat_at
                if elapsed > self.timeout * 3:
                    self.registry.deregister(worker.worker_id)
                    purged += 1
        return purged
