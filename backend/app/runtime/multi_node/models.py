"""
W27-28: Multi-Node Scheduling — 数据模型

跨节点调度的核心数据结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


# ─── Enums ───────────────────────────────────────────────────────────────────


class NodeStatus(str, Enum):
    """节点状态"""
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    DRAINING = "draining"
    MAINTENANCE = "maintenance"
    UNKNOWN = "unknown"


class RoutingStrategy(str, Enum):
    """负载均衡策略"""
    LEAST_LOADED = "least_loaded"
    ROUND_ROBIN = "round_robin"
    CONSISTENT_HASH = "consistent_hash"
    WEIGHTED = "weighted"
    RANDOM = "random"
    GEO_AWARE = "geo_aware"


class TaskMigrationPolicy(str, Enum):
    """任务迁移策略"""
    NO_MIGRATION = "no_migration"
    GRACEFUL = "graceful"
    IMMEDIATE = "immediate"


# ─── Data Classes ────────────────────────────────────────────────────────────


@dataclass
class NodeInfo:
    """集群节点信息"""
    node_id: str = field(default_factory=lambda: str(uuid4()))
    node_name: str = ""
    host: str = "localhost"
    port: int = 8000
    api_prefix: str = "/api/v1"
    status: NodeStatus = NodeStatus.ONLINE
    capabilities: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    # 负载指标
    active_tasks: int = 0
    max_tasks: int = 100
    cpu_usage_percent: float = 0.0
    memory_usage_percent: float = 0.0
    # 网络
    region: str = "default"
    zone: str = "default"
    # 时间戳
    registered_at: datetime = field(default_factory=datetime.now)
    last_heartbeat: datetime = field(default_factory=datetime.now)
    heartbeat_interval_seconds: int = 10
    # 权重
    weight: float = 1.0
    # 运行时版本
    runtime_version: str = "2.0.0"
    python_version: str = ""
    # Token 使用统计
    tokens_used_today: int = 0
    cost_today: float = 0.0

    @property
    def load_ratio(self) -> float:
        """负载比率 (0-1)"""
        if self.max_tasks <= 0:
            return 1.0
        return self.active_tasks / self.max_tasks

    @property
    def is_available(self) -> bool:
        return self.status == NodeStatus.ONLINE and self.load_ratio < 1.0

    @property
    def health_score(self) -> float:
        """健康分数 (0-100)"""
        score = 100.0
        score -= self.load_ratio * 50
        score -= min(self.cpu_usage_percent, 50) * 0.5
        score -= min(self.memory_usage_percent, 50) * 0.3
        if self.status != NodeStatus.ONLINE:
            score -= 30
        return max(0.0, score)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "host": self.host,
            "port": self.port,
            "status": self.status.value,
            "capabilities": self.capabilities,
            "labels": self.labels,
            "active_tasks": self.active_tasks,
            "max_tasks": self.max_tasks,
            "cpu_usage_percent": self.cpu_usage_percent,
            "memory_usage_percent": self.memory_usage_percent,
            "region": self.region,
            "zone": self.zone,
            "registered_at": self.registered_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "weight": self.weight,
            "runtime_version": self.runtime_version,
            "load_ratio": self.load_ratio,
            "is_available": self.is_available,
            "health_score": self.health_score,
        }


@dataclass
class NodeRegistryEntry:
    """节点注册表条目"""
    node: NodeInfo
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutingDecision:
    """路由决策结果"""
    target_node_id: str
    target_host: str
    target_port: int
    strategy_used: RoutingStrategy
    reason: str = ""
    score: float = 0.0
    alternatives: list[str] = field(default_factory=list)
    made_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_node_id": self.target_node_id,
            "target_host": self.target_host,
            "target_port": self.target_port,
            "strategy_used": self.strategy_used.value,
            "reason": self.reason,
            "score": self.score,
            "alternatives": self.alternatives,
            "made_at": self.made_at.isoformat(),
        }


@dataclass
class NodeHeartbeat:
    """节点心跳"""
    node_id: str
    active_tasks: int = 0
    cpu_usage_percent: float = 0.0
    memory_usage_percent: float = 0.0
    tokens_used: int = 0
    cost_used: float = 0.0
    status: NodeStatus = NodeStatus.ONLINE
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "active_tasks": self.active_tasks,
            "cpu_usage_percent": self.cpu_usage_percent,
            "memory_usage_percent": self.memory_usage_percent,
            "tokens_used": self.tokens_used,
            "cost_used": self.cost_used,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class CrossNodeTask:
    """跨节点任务"""
    task_id: str
    source_node_id: str
    target_node_id: str = ""
    capability: str = ""
    priority: int = 5
    workflow_payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    result: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "capability": self.capability,
            "priority": self.priority,
            "status": self.status,
            "result": self.result,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class ClusterTopology:
    """集群拓扑"""
    cluster_id: str = field(default_factory=lambda: str(uuid4()))
    nodes: dict[str, NodeInfo] = field(default_factory=dict)
    total_active_tasks: int = 0
    total_capacity: int = 0
    regions: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "node_count": len(self.nodes),
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "total_active_tasks": self.total_active_tasks,
            "total_capacity": self.total_capacity,
            "regions": self.regions,
            "updated_at": self.updated_at.isoformat(),
        }
