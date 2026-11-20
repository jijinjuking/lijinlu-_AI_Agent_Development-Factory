"""W31-32 Runtime Federation — 数据模型

跨集群运行时联邦的数据模型：成员、集群、策略、同步、跨集群任务。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


# ──────────────────────────────────────────────
# 枚举
# ──────────────────────────────────────────────


class MemberStatus(str, Enum):
    """联邦成员状态"""

    ACTIVE = "active"           # 正常活跃
    DEGRADED = "degraded"       # 部分功能降级
    ISOLATED = "isolated"       # 网络隔离（可能脑裂）
    OFFLINE = "offline"         # 完全离线
    LEAVING = "leaving"         # 正在离开联邦

    @property
    def is_available(self) -> bool:
        return self in (MemberStatus.ACTIVE, MemberStatus.DEGRADED)

    @property
    def is_healthy(self) -> bool:
        return self == MemberStatus.ACTIVE


class SyncStrategy(str, Enum):
    """数据同步策略"""

    NONE = "none"               # 不同步
    PUSH = "push"               # 主动推送
    PULL = "pull"               # 被动拉取
    PUSH_PULL = "push_pull"     # 双向同步
    EVENTUAL = "eventual"       # 最终一致性
    STRONG = "strong"           # 强一致性


class SyncScope(str, Enum):
    """同步范围"""

    STATE_ONLY = "state_only"           # 仅状态
    ARTIFACTS_ONLY = "artifacts_only"   # 仅产物
    CHECKPOINTS_ONLY = "checkpoints_only"  # 仅检查点
    FULL = "full"                        # 全部


class DispatchPolicy(str, Enum):
    """跨集群任务分发策略"""

    LOCAL_FIRST = "local_first"         # 优先本地
    LOAD_BALANCED = "load_balanced"     # 负载均衡
    CAPABILITY_MATCH = "capability_match"  # 能力匹配
    GEO_AFFINITY = "geo_affinity"        # 地理亲和
    COST_OPTIMIZED = "cost_optimized"    # 成本优化
    ROUND_ROBIN = "round_robin"          # 轮询


class FederationRole(str, Enum):
    """联邦成员角色"""

    LEADER = "leader"           # 主节点
    FOLLOWER = "follower"       # 从节点
    OBSERVER = "observer"       # 观察者（只读）
    ARBITER = "arbiter"         # 仲裁者（不执行任务）


class SyncStatus(str, Enum):
    """同步记录状态"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    CONFLICT = "conflict"


# ──────────────────────────────────────────────
# 核心数据类
# ──────────────────────────────────────────────


@dataclass
class FederationMember:
    """联邦成员节点"""

    member_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    cluster_id: str = ""
    role: FederationRole = FederationRole.FOLLOWER
    status: MemberStatus = MemberStatus.ACTIVE
    endpoint: str = ""              # HTTP/gRPC 端点
    capabilities: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    region: str = "default"
    zone: str = "default"
    total_capacity: int = 100       # 总容量（可并发任务数）
    used_capacity: int = 0          # 已用容量

    # 时间戳
    joined_at: datetime = field(default_factory=datetime.now)
    last_heartbeat: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # 运行时指标
    cpu_usage_pct: float = 0.0
    memory_usage_pct: float = 0.0
    active_tasks: int = 0
    total_tasks_completed: int = 0
    avg_task_duration_ms: float = 0.0

    @property
    def load_ratio(self) -> float:
        """负载比率 0.0-1.0"""
        if self.total_capacity <= 0:
            return 1.0
        return min(self.used_capacity / self.total_capacity, 1.0)

    @property
    def available_capacity(self) -> int:
        return max(self.total_capacity - self.used_capacity, 0)

    @property
    def is_available(self) -> bool:
        return self.status.is_available and self.available_capacity > 0

    @property
    def health_score(self) -> float:
        """健康分数 0.0-1.0，综合考虑 CPU/内存/可用容量"""
        cpu_score = max(0.0, 1.0 - self.cpu_usage_pct / 100.0)
        mem_score = max(0.0, 1.0 - self.memory_usage_pct / 100.0)
        cap_score = 1.0 - self.load_ratio
        return round((cpu_score * 0.3 + mem_score * 0.3 + cap_score * 0.4), 4)


@dataclass
class FederationCluster:
    """联邦集群"""

    cluster_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    leader_id: str = ""             # 主节点 member_id
    members: list[str] = field(default_factory=list)  # member_id 列表
    capabilities: list[str] = field(default_factory=list)
    region: str = "default"

    # 集群指标
    total_capacity: int = 0
    used_capacity: int = 0
    active_members: int = 0
    total_members: int = 0

    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class FederationTopology:
    """联邦拓扑视图"""

    federation_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "default-federation"
    clusters: dict[str, FederationCluster] = field(default_factory=dict)
    members: dict[str, FederationMember] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)  # (member_a, member_b)
    snapshot_at: datetime = field(default_factory=datetime.now)


@dataclass
class FederationPolicyConfig:
    """联邦策略配置"""

    policy_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "default"
    dispatch: DispatchPolicy = DispatchPolicy.LOAD_BALANCED
    sync_strategy: SyncStrategy = SyncStrategy.EVENTUAL
    sync_scope: SyncScope = SyncScope.FULL

    # 分发约束
    max_cross_cluster_ratio: float = 0.5   # 跨集群任务最大比例
    prefer_same_region: bool = True         # 优先同区域
    fallback_to_local: bool = True          # 远程不可用时回退本地
    max_retry_cross_cluster: int = 3        # 跨集群重试上限

    # 一致性与安全
    quorum_size: int = 2                    # 法定人数
    require_leader_approval: bool = False   # 跨集群任务是否需 Leader 审批
    encryption_required: bool = False       # 传输是否加密

    # 超时
    sync_timeout_seconds: int = 30
    dispatch_timeout_seconds: int = 60
    heartbeat_interval_seconds: int = 10


@dataclass
class CrossClusterTask:
    """跨集群任务"""

    task_id: str = field(default_factory=lambda: str(uuid4()))
    source_cluster_id: str = ""
    target_cluster_id: str = ""
    target_member_id: str = ""
    capability: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    status: str = "pending"         # pending/dispatched/running/completed/failed/cancelled
    priority: int = 5               # 1(highest)-10(lowest)

    # 时间戳
    created_at: datetime = field(default_factory=datetime.now)
    dispatched_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # 结果
    result: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    retry_count: int = 0

    # 上下文
    requires_state_sync: bool = False
    requires_artifact_sync: bool = False
    artifact_ids: list[str] = field(default_factory=list)


@dataclass
class DataSyncRecord:
    """数据同步记录"""

    sync_id: str = field(default_factory=lambda: str(uuid4()))
    source_member_id: str = ""
    target_member_id: str = ""
    scope: SyncScope = SyncScope.FULL
    strategy: SyncStrategy = SyncStrategy.PUSH
    status: SyncStatus = SyncStatus.PENDING

    # 同步内容摘要
    state_keys: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    checkpoint_ids: list[str] = field(default_factory=list)

    # 时间戳
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # 结果
    items_synced: int = 0
    items_failed: int = 0
    error_message: str = ""
    conflict_details: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FederationStats:
    """联邦统计信息"""

    total_clusters: int = 0
    total_members: int = 0
    active_members: int = 0
    degraded_members: int = 0
    offline_members: int = 0

    total_capacity: int = 0
    used_capacity: int = 0
    overall_load: float = 0.0     # 平均负载率

    total_tasks_completed: int = 0
    active_cross_cluster_tasks: int = 0
    total_syncs_completed: int = 0
    total_syncs_failed: int = 0

    snapshot_at: datetime = field(default_factory=datetime.now)


@dataclass
class MemberHeartbeatRequest:
    """成员心跳请求"""

    member_id: str = ""
    status: MemberStatus = MemberStatus.ACTIVE
    cpu_usage_pct: float = 0.0
    memory_usage_pct: float = 0.0
    active_tasks: int = 0
    used_capacity: int = 0
    total_tasks_completed: int = 0
    avg_task_duration_ms: float = 0.0


@dataclass
class JoinRequest:
    """加入联邦请求"""

    name: str
    endpoint: str
    capabilities: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    region: str = "default"
    zone: str = "default"
    total_capacity: int = 100
    role: FederationRole = FederationRole.FOLLOWER
    cluster_name: str = ""     # 空则自动分配到默认集群


@dataclass
class DispatchRequest:
    """跨集群分发请求"""

    capability: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 5
    target_cluster_id: str = ""        # 空 = 自动选择
    target_member_id: str = ""          # 空 = 自动选择
    policy: DispatchPolicy | None = None  # None = 使用集群默认策略
    requires_state_sync: bool = False
    requires_artifact_sync: bool = False
    artifact_ids: list[str] = field(default_factory=list)


@dataclass
class DispatchResult:
    """分发结果"""

    task_id: str = field(default_factory=lambda: str(uuid4()))
    accepted: bool = False
    target_cluster_id: str = ""
    target_member_id: str = ""
    policy_used: DispatchPolicy = DispatchPolicy.LOAD_BALANCED
    reason: str = ""
    estimated_duration_ms: float = 0.0
