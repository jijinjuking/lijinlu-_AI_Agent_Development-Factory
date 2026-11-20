"""W31-32 Runtime Federation — 联邦策略引擎

管理跨集群任务分发策略、同步策略的决策逻辑。
"""

from __future__ import annotations

import logging

from .models import (
    DispatchPolicy,
    FederationMember,
    FederationPolicyConfig,
    SyncScope,
    SyncStrategy,
)

logger = logging.getLogger(__name__)


class FederationPolicyEngine:
    """联邦策略引擎 — 决定任务如何分发、数据如何同步"""

    def __init__(self, config: FederationPolicyConfig | None = None):
        self._config = config or FederationPolicyConfig()

    # ── 分发策略决策 ──────────────────────────

    def select_target(self, candidates: list[FederationMember],
                      policy: DispatchPolicy | None = None,
                      prefer_region: str = "",
                      task_payload_size: int = 0) -> FederationMember | None:
        """从候选成员中选择目标，按指定策略"""
        if not candidates:
            return None

        policy = policy or self._config.dispatch

        routing_map = {
            DispatchPolicy.LOCAL_FIRST: self._route_local_first,
            DispatchPolicy.LOAD_BALANCED: self._route_load_balanced,
            DispatchPolicy.CAPABILITY_MATCH: self._route_capability_match,
            DispatchPolicy.GEO_AFFINITY: self._route_geo_affinity,
            DispatchPolicy.COST_OPTIMIZED: self._route_cost_optimized,
            DispatchPolicy.ROUND_ROBIN: self._route_round_robin,
        }
        handler = routing_map.get(policy, self._route_load_balanced)
        return handler(candidates, prefer_region, task_payload_size)

    def _route_local_first(self, candidates: list[FederationMember],
                           prefer_region: str, _size: int) -> FederationMember | None:
        """优先选同区域，其次选负载最低"""
        same_region = [m for m in candidates if m.region == prefer_region]
        pool = same_region if same_region else candidates
        return min(pool, key=lambda m: m.load_ratio)

    def _route_load_balanced(self, candidates: list[FederationMember],
                             _region: str, _size: int) -> FederationMember | None:
        """选负载率最低的成员"""
        return min(candidates, key=lambda m: m.load_ratio)

    def _route_capability_match(self, candidates: list[FederationMember],
                                capability: str, _size: int) -> FederationMember | None:
        """选负载最低且有匹配能力的成员（capability 已由调用方过滤）"""
        return min(candidates, key=lambda m: m.load_ratio)

    def _route_geo_affinity(self, candidates: list[FederationMember],
                            prefer_region: str, _size: int) -> FederationMember | None:
        """地理亲和：同区域优先，同区域中负载最低"""
        same_region = [m for m in candidates if m.region == prefer_region]
        if same_region:
            return min(same_region, key=lambda m: m.load_ratio)
        same_zone = [m for m in candidates if m.zone == prefer_region]
        if same_zone:
            return min(same_zone, key=lambda m: m.load_ratio)
        return min(candidates, key=lambda m: m.load_ratio)

    def _route_cost_optimized(self, candidates: list[FederationMember],
                              _region: str, _size: int) -> FederationMember | None:
        """成本优化：选负载适中且健康分数高的成员"""
        def cost_score(m: FederationMember) -> float:
            # 偏好负载 30%-70% 的成员（不太闲也不太忙）
            load = m.load_ratio
            load_ideal = 1.0 - abs(load - 0.5) * 2.0
            return load_ideal * 0.5 + m.health_score * 0.5

        return max(candidates, key=cost_score)

    _round_robin_index: int = 0

    def _route_round_robin(self, candidates: list[FederationMember],
                           _region: str, _size: int) -> FederationMember | None:
        """轮询"""
        n = len(candidates)
        idx = self._round_robin_index % n
        self._round_robin_index += 1
        return candidates[idx]

    # ── 同步策略决策 ──────────────────────────

    def decide_sync(self, source: FederationMember, target: FederationMember,
                    data_size: int = 0) -> tuple[SyncStrategy, SyncScope]:
        """根据成员状态和数据量决定同步策略"""
        strategy = self._config.sync_strategy
        scope = self._config.sync_scope

        # 同集群（非空）→ 可使用强一致性
        if source.cluster_id and target.cluster_id and source.cluster_id == target.cluster_id:
            if strategy == SyncStrategy.EVENTUAL:
                strategy = SyncStrategy.PUSH

        # 跨区域 → 用最终一致性
        if source.region != target.region:
            if strategy in (SyncStrategy.STRONG, SyncStrategy.PUSH_PULL, SyncStrategy.PUSH):
                strategy = SyncStrategy.EVENTUAL

        # 大数据量 → 减少同步范围
        if data_size > 1_000_000:  # >1MB
            if scope == SyncScope.FULL:
                scope = SyncScope.STATE_ONLY

        return strategy, scope

    def should_dispatch_cross_cluster(self, local_member: FederationMember) -> bool:
        """判断是否应该跨集群分发任务"""
        # 本地负载已达上限
        if local_member.available_capacity <= 0:
            return True
        # 本地负载超过 80%
        if local_member.load_ratio > 0.8:
            return True
        # 本地降级
        if local_member.status != "active":
            return True
        return False

    def should_sync_state(self, source: FederationMember,
                          target: FederationMember) -> bool:
        """判断是否需要同步状态"""
        if self._config.sync_strategy == SyncStrategy.NONE:
            return False
        if self._config.sync_scope == SyncScope.ARTIFACTS_ONLY:
            return False
        return True

    # ── Quorum ────────────────────────────────

    def has_quorum(self, members: list[FederationMember]) -> bool:
        """检查是否达到法定人数"""
        active = sum(1 for m in members if m.status == "active")
        return active >= self._config.quorum_size

    # ── 配置 ──────────────────────────────────

    def get_config(self) -> FederationPolicyConfig:
        return self._config

    def update_config(self, **kwargs) -> FederationPolicyConfig:
        """更新策略配置"""
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
        return self._config
