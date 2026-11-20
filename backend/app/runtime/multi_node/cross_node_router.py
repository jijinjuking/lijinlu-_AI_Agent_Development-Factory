"""
W27-28: Multi-Node Scheduling — 跨节点路由

多策略负载均衡路由器：Least-Loaded、Round-Robin、Consistent Hash、Weighted、Random。
"""

from __future__ import annotations

import hashlib
import itertools
import logging
import random
from datetime import datetime
from typing import Any

from app.runtime.multi_node.models import (
    NodeInfo,
    NodeStatus,
    RoutingDecision,
    RoutingStrategy,
)
from app.runtime.multi_node.node_registry import NodeRegistry

logger = logging.getLogger(__name__)


class CrossNodeRouter:
    """跨节点任务路由器 —— 多策略负载均衡"""

    def __init__(self, registry: NodeRegistry):
        self._registry = registry
        self._round_robin_counter: dict[str, itertools.cycle] = {}
        self._hash_ring: list[tuple[int, str]] = []  # (hash, node_id)
        self._virtual_nodes: int = 100

    # ── 主路由接口 ───────────────────────────────────────────────────────

    async def route(
        self,
        capability: str = "",
        strategy: RoutingStrategy = RoutingStrategy.LEAST_LOADED,
        region: str = "",
        task_id: str = "",
    ) -> RoutingDecision | None:
        """选择最佳目标节点"""
        nodes = await self._get_candidate_nodes(capability, region)
        if not nodes:
            logger.warning(f"CrossNodeRouter: no available nodes for capability={capability}")
            return None

        routing_map = {
            RoutingStrategy.LEAST_LOADED: self._route_least_loaded,
            RoutingStrategy.ROUND_ROBIN: self._route_round_robin,
            RoutingStrategy.CONSISTENT_HASH: self._route_consistent_hash,
            RoutingStrategy.WEIGHTED: self._route_weighted,
            RoutingStrategy.RANDOM: self._route_random,
        }

        handler = routing_map.get(strategy, self._route_least_loaded)
        decision = await handler(nodes, task_id)

        if decision:
            decision.strategy_used = strategy

        return decision

    async def route_batch(
        self,
        tasks: list[dict[str, Any]],
        capability: str = "",
        strategy: RoutingStrategy = RoutingStrategy.LEAST_LOADED,
    ) -> list[tuple[str, RoutingDecision | None]]:
        """批量路由（每个任务可能不同节点）"""
        results = []
        for task in tasks:
            task_id = task.get("task_id", "")
            decision = await self.route(
                capability=capability or task.get("capability", ""),
                strategy=strategy,
                region=task.get("region", ""),
                task_id=task_id,
            )
            results.append((task_id, decision))
        return results

    # ── 路由策略实现 ─────────────────────────────────────────────────────

    async def _route_least_loaded(
        self, nodes: list[NodeInfo], task_id: str = ""
    ) -> RoutingDecision | None:
        """最少负载策略"""
        best = min(nodes, key=lambda n: (n.load_ratio, n.cpu_usage_percent))
        return RoutingDecision(
            target_node_id=best.node_id,
            target_host=best.host,
            target_port=best.port,
            strategy_used=RoutingStrategy.LEAST_LOADED,
            reason=f"Load ratio: {best.load_ratio:.2f}, CPU: {best.cpu_usage_percent:.1f}%",
            score=best.health_score,
        )

    async def _route_round_robin(
        self, nodes: list[NodeInfo], task_id: str = ""
    ) -> RoutingDecision | None:
        """轮询策略"""
        capability = nodes[0].capabilities[0] if nodes[0].capabilities else "default"
        if capability not in self._round_robin_counter:
            self._round_robin_counter[capability] = itertools.cycle(nodes)
        selected = next(self._round_robin_counter[capability])
        return RoutingDecision(
            target_node_id=selected.node_id,
            target_host=selected.host,
            target_port=selected.port,
            strategy_used=RoutingStrategy.ROUND_ROBIN,
            reason=f"Round-robin selection",
            score=selected.health_score,
        )

    async def _route_consistent_hash(
        self, nodes: list[NodeInfo], task_id: str = ""
    ) -> RoutingDecision | None:
        """一致性哈希策略"""
        if not task_id:
            task_id = str(datetime.now().timestamp())

        ring = self._build_hash_ring(nodes)
        task_hash = self._hash_key(task_id)

        # 顺时针查找最近的节点
        for node_hash, node_id in ring:
            if node_hash >= task_hash:
                selected = next((n for n in nodes if n.node_id == node_id), None)
                if selected:
                    return RoutingDecision(
                        target_node_id=selected.node_id,
                        target_host=selected.host,
                        target_port=selected.port,
                        strategy_used=RoutingStrategy.CONSISTENT_HASH,
                        reason=f"Hash: {task_hash} → node {node_id[:8]}",
                        score=selected.health_score,
                    )

        # 回到环的起点
        if ring:
            first_node_id = ring[0][1]
            selected = next((n for n in nodes if n.node_id == first_node_id), None)
            if selected:
                return RoutingDecision(
                    target_node_id=selected.node_id,
                    target_host=selected.host,
                    target_port=selected.port,
                    strategy_used=RoutingStrategy.CONSISTENT_HASH,
                    reason=f"Hash wrap: {task_hash} → node {first_node_id[:8]}",
                    score=selected.health_score,
                )

        return None

    async def _route_weighted(
        self, nodes: list[NodeInfo], task_id: str = ""
    ) -> RoutingDecision | None:
        """加权随机策略"""
        total_weight = sum(n.weight for n in nodes)
        if total_weight <= 0:
            return await self._route_random(nodes, task_id)

        r = random.uniform(0, total_weight)
        cumulative = 0.0
        for node in nodes:
            cumulative += node.weight
            if r <= cumulative:
                return RoutingDecision(
                    target_node_id=node.node_id,
                    target_host=node.host,
                    target_port=node.port,
                    strategy_used=RoutingStrategy.WEIGHTED,
                    reason=f"Weight: {node.weight}/{total_weight}",
                    score=node.health_score,
                )

        # fallback
        selected = nodes[-1]
        return RoutingDecision(
            target_node_id=selected.node_id,
            target_host=selected.host,
            target_port=selected.port,
            strategy_used=RoutingStrategy.WEIGHTED,
            reason="Weighted fallback",
            score=selected.health_score,
        )

    async def _route_random(
        self, nodes: list[NodeInfo], task_id: str = ""
    ) -> RoutingDecision | None:
        """随机策略"""
        selected = random.choice(nodes)
        return RoutingDecision(
            target_node_id=selected.node_id,
            target_host=selected.host,
            target_port=selected.port,
            strategy_used=RoutingStrategy.RANDOM,
            reason="Random selection",
            score=selected.health_score,
        )

    # ── 辅助方法 ─────────────────────────────────────────────────────────

    async def _get_candidate_nodes(
        self, capability: str, region: str
    ) -> list[NodeInfo]:
        """获取候选节点列表"""
        if capability:
            nodes = await self._registry.get_nodes_by_capability(capability)
        else:
            nodes = await self._registry.get_available_nodes()

        if region:
            nodes = [n for n in nodes if n.region == region]

        return nodes

    def _build_hash_ring(self, nodes: list[NodeInfo]) -> list[tuple[int, str]]:
        """构建一致性哈希环"""
        ring: list[tuple[int, str]] = []
        for node in nodes:
            for v in range(self._virtual_nodes):
                key = f"{node.node_id}:v{v}"
                ring.append((self._hash_key(key), node.node_id))
        ring.sort(key=lambda x: x[0])
        return ring

    @staticmethod
    def _hash_key(key: str) -> int:
        """对 key 计算 32 位哈希"""
        return int(hashlib.md5(key.encode()).hexdigest()[:8], 16)
