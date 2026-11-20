"""
W27-28: Multi-Node Scheduling — 节点注册中心

管理集群中所有节点的注册、发现、心跳和状态维护。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from app.runtime.multi_node.models import (
    NodeHeartbeat,
    NodeInfo,
    NodeStatus,
)

logger = logging.getLogger(__name__)


class NodeRegistry:
    """集群节点注册中心"""

    def __init__(
        self,
        heartbeat_timeout_seconds: int = 30,
        cleanup_interval_seconds: int = 30,
    ):
        self._nodes: dict[str, NodeInfo] = {}
        self._lock = asyncio.Lock()
        self._heartbeat_timeout = heartbeat_timeout_seconds
        self._cleanup_interval = cleanup_interval_seconds
        self._cleanup_task: asyncio.Task | None = None
        self._running = False
        self._event_listeners: list[callable] = []

    # ── 生命周期 ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """启动注册中心（开始自动清理）"""
        if self._running:
            return
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("NodeRegistry: started")

    async def stop(self) -> None:
        """停止注册中心"""
        self._running = False
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    # ── 节点注册 ─────────────────────────────────────────────────────────

    async def register(self, node: NodeInfo) -> NodeInfo:
        """注册或更新节点"""
        async with self._lock:
            existing = self._nodes.get(node.node_id)
            if existing:
                # 更新已有节点
                existing.host = node.host
                existing.port = node.port
                existing.capabilities = node.capabilities
                existing.labels = node.labels
                existing.max_tasks = node.max_tasks
                existing.region = node.region
                existing.zone = node.zone
                existing.weight = node.weight
                existing.runtime_version = node.runtime_version
                existing.last_heartbeat = datetime.now()
                existing.status = node.status
                logger.debug(f"NodeRegistry: updated node {node.node_id}")
                self._notify_listeners("node_updated", existing)
                return existing
            else:
                # 新节点
                node.registered_at = datetime.now()
                node.last_heartbeat = datetime.now()
                self._nodes[node.node_id] = node
                logger.info(f"NodeRegistry: registered node {node.node_id} ({node.node_name})")
                self._notify_listeners("node_registered", node)
                return node

    async def deregister(self, node_id: str) -> bool:
        """注销节点"""
        async with self._lock:
            node = self._nodes.pop(node_id, None)
            if node:
                node.status = NodeStatus.OFFLINE
                logger.info(f"NodeRegistry: deregistered node {node_id}")
                self._notify_listeners("node_deregistered", node)
                return True
            return False

    async def update_node_status(self, node_id: str, status: NodeStatus) -> bool:
        """更新节点状态（如设置 DRAINING/ONLINE）"""
        async with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return False
            node.status = status
            logger.info(f"NodeRegistry: node {node_id} status -> {status.value}")
            self._notify_listeners("node_status_changed", node)
            return True

    async def heartbeat(self, heartbeat: NodeHeartbeat) -> bool:
        """处理节点心跳"""
        async with self._lock:
            node = self._nodes.get(heartbeat.node_id)
            if not node:
                logger.warning(f"NodeRegistry: heartbeat from unknown node {heartbeat.node_id}")
                return False

            node.active_tasks = heartbeat.active_tasks
            node.cpu_usage_percent = heartbeat.cpu_usage_percent
            node.memory_usage_percent = heartbeat.memory_usage_percent
            node.tokens_used_today += heartbeat.tokens_used
            node.cost_today += heartbeat.cost_used
            node.last_heartbeat = heartbeat.timestamp
            node.status = heartbeat.status
            return True

    # ── 节点发现 ─────────────────────────────────────────────────────────

    async def get_node(self, node_id: str) -> NodeInfo | None:
        """获取节点信息"""
        async with self._lock:
            return self._nodes.get(node_id)

    async def list_nodes(self, status_filter: str = "") -> list[NodeInfo]:
        """列出所有节点"""
        async with self._lock:
            nodes = list(self._nodes.values())
        if status_filter:
            nodes = [n for n in nodes if n.status.value == status_filter]
        return sorted(nodes, key=lambda n: n.node_name)

    async def get_available_nodes(self) -> list[NodeInfo]:
        """获取可用节点（在线且未满载）"""
        nodes = await self.list_nodes(status_filter="online")
        return [n for n in nodes if n.is_available]

    async def get_nodes_by_capability(self, capability: str) -> list[NodeInfo]:
        """按能力筛选节点"""
        nodes = await self.get_available_nodes()
        return [n for n in nodes if capability in n.capabilities]

    async def get_nodes_by_region(self, region: str) -> list[NodeInfo]:
        """按区域筛选节点"""
        nodes = await self.get_available_nodes()
        return [n for n in nodes if n.region == region]

    async def get_cluster_stats(self) -> dict[str, Any]:
        """获取集群统计"""
        async with self._lock:
            nodes = list(self._nodes.values())

        online = [n for n in nodes if n.status == NodeStatus.ONLINE]
        return {
            "total_nodes": len(nodes),
            "online_nodes": len(online),
            "offline_nodes": len([n for n in nodes if n.status == NodeStatus.OFFLINE]),
            "degraded_nodes": len([n for n in nodes if n.status == NodeStatus.DEGRADED]),
            "total_active_tasks": sum(n.active_tasks for n in nodes),
            "total_capacity": sum(n.max_tasks for n in nodes),
            "total_tokens_today": sum(n.tokens_used_today for n in nodes),
            "total_cost_today": round(sum(n.cost_today for n in nodes), 4),
            "regions": list(set(n.region for n in nodes)),
            "avg_load_ratio": round(
                sum(n.load_ratio for n in online) / len(online) if online else 0, 2
            ),
        }

    async def get_least_loaded_node(
        self, capability: str = "", region: str = ""
    ) -> NodeInfo | None:
        """获取负载最小的节点"""
        nodes = await self.get_available_nodes()
        if capability:
            nodes = [n for n in nodes if capability in n.capabilities]
        if region:
            nodes = [n for n in nodes if n.region == region]
        if not nodes:
            return None
        return min(nodes, key=lambda n: (n.load_ratio, n.cpu_usage_percent))

    # ── 事件监听 ─────────────────────────────────────────────────────────

    def add_listener(self, callback: callable) -> None:
        """添加节点事件监听器"""
        self._event_listeners.append(callback)

    def remove_listener(self, callback: callable) -> None:
        """移除节点事件监听器"""
        if callback in self._event_listeners:
            self._event_listeners.remove(callback)

    def _notify_listeners(self, event: str, node: NodeInfo) -> None:
        for cb in self._event_listeners:
            try:
                cb(event, node)
            except Exception as exc:
                logger.warning(f"NodeRegistry: listener error: {exc}")

    # ── 内部方法 ─────────────────────────────────────────────────────────

    async def _cleanup_loop(self) -> None:
        """定期清理超时节点"""
        while self._running:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_stale_nodes()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"NodeRegistry: cleanup error: {exc}")

    async def _cleanup_stale_nodes(self) -> int:
        """清理心跳超时的节点"""
        cutoff = datetime.now() - timedelta(seconds=self._heartbeat_timeout)
        stale_ids = []

        async with self._lock:
            for nid, node in self._nodes.items():
                if node.last_heartbeat < cutoff and node.status == NodeStatus.ONLINE:
                    node.status = NodeStatus.OFFLINE
                    stale_ids.append(nid)

        for nid in stale_ids:
            logger.warning(f"NodeRegistry: node {nid} marked offline (heartbeat timeout)")
            async with self._lock:
                node = self._nodes.get(nid)
                if node:
                    self._notify_listeners("node_offline", node)

        return len(stale_ids)
