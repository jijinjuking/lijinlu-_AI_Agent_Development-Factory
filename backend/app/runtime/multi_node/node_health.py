"""
W27-28: Multi-Node Scheduling — 节点健康检查

通过 HTTP 对各节点进行定期健康检查和性能探测。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

import aiohttp

from app.runtime.multi_node.models import (
    NodeHeartbeat,
    NodeInfo,
    NodeStatus,
)
from app.runtime.multi_node.node_registry import NodeRegistry

logger = logging.getLogger(__name__)


class NodeHealthChecker:
    """节点健康检查器 —— 定期 HTTP 探测"""

    def __init__(
        self,
        registry: NodeRegistry,
        check_interval_seconds: int = 15,
        request_timeout_seconds: int = 5,
        unhealthy_threshold: int = 3,
        healthy_threshold: int = 2,
    ):
        self._registry = registry
        self._check_interval = check_interval_seconds
        self._request_timeout = request_timeout_seconds
        self._unhealthy_threshold = unhealthy_threshold
        self._healthy_threshold = healthy_threshold
        self._failure_counts: dict[str, int] = {}
        self._success_counts: dict[str, int] = {}
        self._check_task: asyncio.Task | None = None
        self._running = False
        self._session: aiohttp.ClientSession | None = None

    # ── 生命周期 ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self._request_timeout)
        )
        self._check_task = asyncio.create_task(self._health_check_loop())
        logger.info("NodeHealthChecker: started")

    async def stop(self) -> None:
        self._running = False
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
            self._session = None

    # ── 健康探测 ─────────────────────────────────────────────────────────

    async def check_node(self, node: NodeInfo) -> dict[str, Any]:
        """对单个节点执行健康检查"""
        url = f"http://{node.host}:{node.port}{node.api_prefix}/health"
        start = time.monotonic()

        try:
            async with self._session.get(url) as resp:
                latency_ms = (time.monotonic() - start) * 1000
                data = await resp.json()

                is_healthy = resp.status == 200

                # 心跳
                heartbeat = NodeHeartbeat(
                    node_id=node.node_id,
                    active_tasks=data.get("active_tasks", 0),
                    cpu_usage_percent=data.get("cpu_usage_percent", 0.0),
                    tokens_used=data.get("tokens_used", 0),
                    status=NodeStatus.ONLINE if is_healthy else NodeStatus.DEGRADED,
                    timestamp=datetime.now(),
                )
                await self._registry.heartbeat(heartbeat)

                return {
                    "node_id": node.node_id,
                    "healthy": is_healthy,
                    "status_code": resp.status,
                    "latency_ms": round(latency_ms, 2),
                    "response": data,
                }
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.debug(f"NodeHealthChecker: {node.node_id} unreachable: {exc}")
            self._failure_counts[node.node_id] = self._failure_counts.get(node.node_id, 0) + 1

            # 连续失败 → 标记离线
            if self._failure_counts[node.node_id] >= self._unhealthy_threshold:
                await self._registry.deregister(node.node_id)

            return {
                "node_id": node.node_id,
                "healthy": False,
                "error": str(exc),
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }

    async def check_all(self) -> dict[str, Any]:
        """对所有注册节点执行健康检查"""
        nodes = await self._registry.list_nodes()
        results = {}
        for node in nodes:
            results[node.node_id] = await self.check_node(node)

        healthy = sum(1 for r in results.values() if r.get("healthy"))
        return {
            "total": len(nodes),
            "healthy": healthy,
            "unhealthy": len(nodes) - healthy,
            "results": results,
        }

    async def get_probe_stats(self) -> dict[str, Any]:
        """获取探测统计"""
        return {
            "failure_counts": dict(self._failure_counts),
            "success_counts": dict(self._success_counts),
            "unhealthy_threshold": self._unhealthy_threshold,
            "healthy_threshold": self._healthy_threshold,
        }

    # ── 内部循环 ─────────────────────────────────────────────────────────

    async def _health_check_loop(self) -> None:
        while self._running:
            try:
                await self.check_all()
            except Exception as exc:
                logger.error(f"NodeHealthChecker: loop error: {exc}")

            try:
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
