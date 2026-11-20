"""
W27-28: Multi-Node Scheduling — 多节点感知调度器

集成 NodeRegistry + CrossNodeRouter + NodeHealthChecker，
提供统一的多节点任务调度入口。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.runtime.multi_node.cross_node_router import CrossNodeRouter
from app.runtime.multi_node.models import (
    CrossNodeTask,
    NodeHeartbeat,
    NodeInfo,
    NodeStatus,
    RoutingDecision,
    RoutingStrategy,
    TaskMigrationPolicy,
)
from app.runtime.multi_node.node_health import NodeHealthChecker
from app.runtime.multi_node.node_registry import NodeRegistry

logger = logging.getLogger(__name__)


class MultiNodeScheduler:
    """多节点感知调度器"""

    def __init__(
        self,
        node_name: str = "",
        node_host: str = "127.0.0.1",
        node_port: int = 8000,
        capabilities: list[str] | None = None,
        max_tasks: int = 100,
        routing_strategy: RoutingStrategy = RoutingStrategy.LEAST_LOADED,
    ):
        self._this_node = NodeInfo(
            node_name=node_name or f"node-{id(self):x}",
            host=node_host,
            port=node_port,
            capabilities=capabilities or ["langgraph_worker", "code_generation"],
            max_tasks=max_tasks,
        )
        self._registry = NodeRegistry()
        self._router = CrossNodeRouter(self._registry)
        self._health_checker = NodeHealthChecker(self._registry)
        self._routing_strategy = routing_strategy
        self._running = False
        self._active_local_tasks: dict[str, CrossNodeTask] = {}
        self._active_remote_tasks: dict[str, CrossNodeTask] = {}
        self._dispatched_tasks: dict[str, dict[str, Any]] = {}

    # ── 生命周期 ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        # 注册自身
        await self._registry.register(self._this_node)
        await self._registry.start()
        await self._health_checker.start()

        logger.info(
            f"MultiNodeScheduler: started as {self._this_node.node_name} "
            f"({self._this_node.host}:{self._this_node.port})"
        )

    async def stop(self) -> None:
        self._running = False
        await self._health_checker.stop()
        await self._registry.stop()
        await self._registry.deregister(self._this_node.node_id)
        logger.info("MultiNodeScheduler: stopped")

    # ── 任务调度 ─────────────────────────────────────────────────────────

    async def schedule_task(
        self,
        task_id: str,
        capability: str = "",
        workflow_payload: dict[str, Any] | None = None,
        strategy: RoutingStrategy | None = None,
        region: str = "",
    ) -> RoutingDecision | None:
        """调度任务到最佳节点"""
        strategy = strategy or self._routing_strategy
        decision = await self._router.route(
            capability=capability,
            strategy=strategy,
            region=region,
            task_id=task_id,
        )

        if decision is None:
            logger.warning(f"MultiNodeScheduler: no target for task {task_id}")
            return None

        task = CrossNodeTask(
            task_id=task_id,
            source_node_id=self._this_node.node_id,
            target_node_id=decision.target_node_id,
            capability=capability,
            workflow_payload=workflow_payload or {},
            status="dispatched",
        )

        if decision.target_node_id == self._this_node.node_id:
            self._active_local_tasks[task_id] = task
            logger.info(f"MultiNodeScheduler: task {task_id} → LOCAL (self)")
        else:
            self._active_remote_tasks[task_id] = task
            logger.info(
                f"MultiNodeScheduler: task {task_id} → REMOTE "
                f"({decision.target_node_id} at {decision.target_host})"
            )

        # 记录分派关系供查询
        self._dispatched_tasks[task_id] = {
            "assigned_node": decision.target_node_id,
            "capability": capability,
            "status": "dispatched",
        }

        return decision

    async def schedule_batch(
        self,
        tasks: list[dict[str, Any]],
        capability: str = "",
        strategy: RoutingStrategy | None = None,
    ) -> list[tuple[str, RoutingDecision | None]]:
        """批量调度"""
        strategy = strategy or self._routing_strategy
        decisions = []
        for task in tasks:
            task_id = task.get("task_id", "")
            decision = await self.schedule_task(
                task_id=task_id,
                capability=capability or task.get("capability", ""),
                workflow_payload=task.get("workflow_payload"),
                strategy=strategy,
                region=task.get("region", ""),
            )
            decisions.append((task_id, decision))
        return decisions

    async def complete_task(self, task_id: str, result: dict[str, Any] | None = None) -> bool:
        """标记任务完成（本地任务完成回调）"""
        task = self._active_local_tasks.pop(task_id, None) or \
               self._active_remote_tasks.pop(task_id, None)
        if task:
            task.status = "completed"
            task.result = result or {}
            task.completed_at = __import__("datetime").datetime.now()
            if task_id in self._dispatched_tasks:
                self._dispatched_tasks[task_id]["status"] = "completed"
            logger.info(f"MultiNodeScheduler: task {task_id} completed")
            return True
        return False

    # ── 节点管理 ─────────────────────────────────────────────────────────

    async def register_peer(self, peer: NodeInfo) -> NodeInfo:
        """注册对等节点"""
        return await self._registry.register(peer)

    async def deregister_peer(self, node_id: str) -> bool:
        """注销对等节点"""
        return await self._registry.deregister(node_id)

    async def send_heartbeat(self) -> NodeHeartbeat:
        """发送本节点心跳"""
        heartbeat = NodeHeartbeat(
            node_id=self._this_node.node_id,
            active_tasks=len(self._active_local_tasks),
            cpu_usage_percent=0.0,  # 实际部署时从系统获取
            timestamp=__import__("datetime").datetime.now(),
        )
        await self._registry.heartbeat(heartbeat)
        return heartbeat

    # ── 查询接口 ─────────────────────────────────────────────────────────

    async def get_cluster_topology(self) -> dict[str, Any]:
        """获取集群拓扑"""
        nodes = await self._registry.list_nodes()
        stats = await self._registry.get_cluster_stats()

        return {
            "this_node": self._this_node.to_dict(),
            "stats": stats,
            "peers": [n.to_dict() for n in nodes if n.node_id != self._this_node.node_id],
            "active_local_tasks": len(self._active_local_tasks),
            "active_remote_tasks": len(self._active_remote_tasks),
            "routing_strategy": self._routing_strategy.value,
        }

    async def list_peers(self, status_filter: str = "") -> list[dict[str, Any]]:
        """列出所有对等节点"""
        nodes = await self._registry.list_nodes(status_filter=status_filter)
        return [n.to_dict() for n in nodes if n.node_id != self._this_node.node_id]

    async def get_node_detail(self, node_id: str) -> dict[str, Any] | None:
        """获取节点详情"""
        node = await self._registry.get_node(node_id)
        return node.to_dict() if node else None

    async def set_node_draining(self, node_id: str, draining: bool) -> bool:
        """设置节点排空状态"""
        status = NodeStatus.DRAINING if draining else NodeStatus.ONLINE
        return await self._registry.update_node_status(node_id, status)

    async def get_node_tasks(self, node_id: str, status: str = "") -> list[dict[str, Any]]:
        """获取指定节点的任务列表"""
        tasks = []
        for tid, task in self._dispatched_tasks.items():
            if task.get("assigned_node") == node_id:
                if not status or task.get("status") == status:
                    tasks.append({"task_id": tid, **task})
        return tasks

    @property
    def this_node_id(self) -> str:
        return self._this_node.node_id

    @property
    def this_node_name(self) -> str:
        return self._this_node.node_name
