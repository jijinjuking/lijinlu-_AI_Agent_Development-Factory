"""
AI Runtime OS — Multi-Node Scheduling (W27-28)

跨节点任务调度系统，支持：
- NodeRegistry: 节点注册、发现、心跳
- CrossNodeRouter: 多策略负载均衡路由器
- NodeHealthChecker: HTTP 健康检查
- MultiNodeScheduler: 多节点感知的统一调度器

调度策略:
- LEAST_LOADED: 最少负载优先
- ROUND_ROBIN: 轮询
- CONSISTENT_HASH: 一致性哈希
- WEIGHTED: 加权随机
- RANDOM: 随机
"""

from app.runtime.multi_node.models import (
    ClusterTopology,
    CrossNodeTask,
    NodeHeartbeat,
    NodeInfo,
    NodeRegistryEntry,
    NodeStatus,
    RoutingDecision,
    RoutingStrategy,
    TaskMigrationPolicy,
)
from app.runtime.multi_node.node_registry import NodeRegistry
from app.runtime.multi_node.cross_node_router import CrossNodeRouter
from app.runtime.multi_node.node_health import NodeHealthChecker
from app.runtime.multi_node.node_scheduler import MultiNodeScheduler

__all__ = [
    # Models
    "NodeInfo",
    "NodeStatus",
    "NodeRegistryEntry",
    "NodeHeartbeat",
    "RoutingDecision",
    "RoutingStrategy",
    "CrossNodeTask",
    "ClusterTopology",
    "TaskMigrationPolicy",
    # Components
    "NodeRegistry",
    "CrossNodeRouter",
    "NodeHealthChecker",
    "MultiNodeScheduler",
]
