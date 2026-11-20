"""W31-32 Runtime Federation — 跨集群运行时联邦

Federation 模块提供多 Runtime 集群间的联邦能力：
- FederationRegistry：成员注册中心（join/leave/heartbeat/选举）
- FederationGateway：跨集群任务分发网关
- StateSyncEngine：跨集群状态同步引擎
- FederationPolicyEngine：分发与同步策略引擎

公共 API：
  Core: FederationRegistry, FederationGateway, StateSyncEngine, FederationPolicyEngine
  Models: FederationMember, FederationCluster, FederationPolicyConfig, CrossClusterTask,
          DataSyncRecord, DispatchRequest, DispatchResult, FederationStats,
          JoinRequest, MemberHeartbeatRequest, FederationTopology
  Enums: MemberStatus, SyncStrategy, SyncScope, DispatchPolicy, FederationRole, SyncStatus
"""

from app.runtime.federation.gateway import FederationGateway
from app.runtime.federation.models import (
    CrossClusterTask,
    DataSyncRecord,
    DispatchPolicy,
    DispatchRequest,
    DispatchResult,
    FederationCluster,
    FederationMember,
    FederationPolicyConfig,
    FederationRole,
    FederationStats,
    FederationTopology,
    JoinRequest,
    MemberHeartbeatRequest,
    MemberStatus,
    SyncScope,
    SyncStatus,
    SyncStrategy,
)
from app.runtime.federation.policy import FederationPolicyEngine
from app.runtime.federation.registry import FederationRegistry
from app.runtime.federation.state_sync import StateSyncEngine

__all__ = [
    # Core
    "FederationRegistry",
    "FederationGateway",
    "StateSyncEngine",
    "FederationPolicyEngine",
    # Models
    "FederationMember",
    "FederationCluster",
    "FederationPolicyConfig",
    "CrossClusterTask",
    "DataSyncRecord",
    "DispatchRequest",
    "DispatchResult",
    "FederationStats",
    "JoinRequest",
    "MemberHeartbeatRequest",
    "FederationTopology",
    # Enums
    "MemberStatus",
    "SyncStrategy",
    "SyncScope",
    "DispatchPolicy",
    "FederationRole",
    "SyncStatus",
]
