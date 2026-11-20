"""
Model Router — 核心路由器

路由策略（按优先级）：
1. 能力路由 — 筛选满足所需能力的模型
2. 复杂度路由 — 匹配任务复杂度等级
3. 成本路由 — 在候选模型中选性价比最高的
4. 回退链 — 主模型不可用时自动切换备选
5. 策略集成 — 与 Policy Engine 联动（预算检查）

用法:
    router = ModelRouter()
    decision = await router.route(
        task_type="code_generation",
        complexity=7,
        required_caps={ModelCapability.CODE_GENERATION, ModelCapability.REASONING},
        max_budget=0.01,  # 最大单次费用 USD
    )
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from app.runtime.model_router.models import (
    ModelSpec, ModelCapability, ComplexityTier,
    RoutingDecision, complexity_from_score,
)
from app.runtime.model_router.model_registry import ModelRegistry, model_registry
from app.runtime.model_router.scoring import ModelScorer, default_scorer, ScoredModel


class RouterStrategy:
    """路由策略枚举（调参用）"""

    CAPABILITY_FIRST = "capability_first"   # 能力优先（默认）
    COST_FIRST = "cost_first"               # 成本优先
    LOCAL_FIRST = "local_first"             # 本地优先（隐私）
    PERFORMANCE_FIRST = "performance_first"  # 性能优先


class ModelRouter:
    """
    动态模型路由器。

    集成到 Scheduler 的 _select_model() 中：
        decision = await model_router.route(...)
        model_name = decision.model.name
    """

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        scorer: ModelScorer | None = None,
        strategy: str = RouterStrategy.CAPABILITY_FIRST,
        fallback_enabled: bool = True,
    ):
        self._registry = registry or model_registry
        self._scorer = scorer or default_scorer
        self._strategy = strategy
        self._fallback_enabled = fallback_enabled
        self._lock = asyncio.Lock()

        # 路由统计
        self._routing_count: dict[str, int] = {}    # model_name → count
        self._fallback_count: int = 0

    # ── 主路由入口 ──

    async def route(
        self,
        task_type: str = "",
        complexity: int = 5,
        required_capabilities: set[ModelCapability] | None = None,
        preferred_model: str = "",
        max_budget: float = 0.0,
        prefer_local: bool = False,
        exclude_models: set[str] | None = None,
    ) -> RoutingDecision:
        """
        核心路由方法。

        Args:
            task_type: 任务类型标识（如 "code_generation"）
            complexity: 任务复杂度 1-10
            required_capabilities: 必需的能力集合
            preferred_model: 用户偏好模型（跳过评分直接选用）
            max_budget: 最大单次费用 (USD)，0 表示不限
            prefer_local: 是否偏好本地模型
            exclude_models: 排除的模型名

        Returns:
            RoutingDecision 包含选中的模型 + 备选列表 + 原因
        """
        required = required_capabilities or set()
        target_tier = complexity_from_score(complexity)
        excluded = exclude_models or set()

        # 1. 用户指定模型 — 直接使用（如果可用）
        if preferred_model:
            spec = self._registry.get(preferred_model)
            if spec and spec.available and spec.name not in excluded:
                if not required or required.issubset(spec.capabilities):
                    return RoutingDecision(
                        model=spec,
                        reason=f"用户指定模型: {preferred_model}",
                        alternatives=[],
                        estimated_cost=self._estimate_cost(spec),
                    )

        # 2. 能力筛选
        candidates = self._registry.find_by_capabilities(required, available_only=True)

        # 如果没有完全满足的，找部分满足的
        if not candidates and required:
            all_available = [
                m for m in self._registry.list_all(available_only=True)
                if m.name not in excluded
            ]
            if all_available:
                # 按能力匹配度排序取前5
                candidates = sorted(
                    all_available,
                    key=lambda m: len(required & m.capabilities),
                    reverse=True,
                )[:5]

        # 如果还是没有候选，返回第一个可用模型
        if not candidates:
            all_available = [
                m for m in self._registry.list_all(available_only=True)
                if m.name not in excluded
            ]
            if not all_available:
                raise RuntimeError("无可用模型")
            candidates = all_available[:1]

        # 3. 排除指定模型
        candidates = [m for m in candidates if m.name not in excluded]
        if not candidates:
            raise RuntimeError("所有候选模型均在排除列表中")

        # 4. 评分 + 排序
        scored = self._scorer.score(
            candidates=candidates,
            required_capabilities=required,
            target_tier=target_tier,
            prefer_local=prefer_local,
        )

        # 5. 策略调优
        best = self._apply_strategy(scored)

        # 6. 预算检查
        estimated = self._estimate_cost(best.spec)
        if max_budget > 0 and estimated > max_budget:
            # 尝试找预算内的较便宜模型
            for sm in scored[1:]:
                alt_cost = self._estimate_cost(sm.spec)
                if alt_cost <= max_budget:
                    best = sm
                    estimated = alt_cost
                    break

        # 7. 备选列表（第二名往后）
        alternatives = [sm.spec for sm in scored[1:4]] if len(scored) > 1 else []

        # 8. 生成路由原因
        reason = self._build_reason(best, target_tier, required)

        # 9. 更新统计
        async with self._lock:
            self._routing_count[best.spec.name] = (
                self._routing_count.get(best.spec.name, 0) + 1
            )

        return RoutingDecision(
            model=best.spec,
            reason=reason,
            alternatives=alternatives,
            estimated_cost=estimated,
            estimated_tokens=self._estimate_tokens(target_tier),
        )

    # ── 回退路由 ──

    async def route_with_fallback(
        self,
        task_type: str = "",
        complexity: int = 5,
        required_capabilities: set[ModelCapability] | None = None,
        preferred_model: str = "",
        max_budget: float = 0.0,
        prefer_local: bool = False,
    ) -> RoutingDecision:
        """
        带自动回退的路由。
        如果主模型失败，自动尝试备选。
        """
        excluded: set[str] = set()

        while True:
            try:
                decision = await self.route(
                    task_type=task_type,
                    complexity=complexity,
                    required_capabilities=required_capabilities,
                    preferred_model=preferred_model if not excluded else "",
                    max_budget=max_budget,
                    prefer_local=prefer_local,
                    exclude_models=excluded,
                )
                return decision
            except RuntimeError:
                raise

    async def on_model_failure(self, model_name: str) -> ModelSpec | None:
        """
        模型调用失败时的回退处理。
        返回备选模型，同时更新统计。

        Args:
            model_name: 失败的模型名

        Returns:
            备选模型（下一个评分最高的可用模型），或 None
        """
        async with self._lock:
            self._fallback_count += 1

        # 获取所有可用模型（排除失败的）
        candidates = [
            m for m in self._registry.list_all(available_only=True)
            if m.name != model_name
        ]
        if not candidates:
            return None

        # 与原模型同 provider 优先（减少 API 切换成本）
        failed = self._registry.get(model_name)
        same_provider = [m for m in candidates if failed and m.provider == failed.provider]

        if same_provider:
            # 在同 provider 中找同 tier 或更低
            if failed:
                same_tier = [m for m in same_provider if m.complexity_tier == failed.complexity_tier]
                if same_tier:
                    return same_tier[0]
            return same_provider[0]

        return candidates[0]

    # ── 内部方法 ──

    def _apply_strategy(self, scored: list[ScoredModel]) -> ScoredModel:
        """根据策略选择模型"""
        if self._strategy == RouterStrategy.COST_FIRST:
            # 按成本排序（最便宜优先）
            sorted_by_cost = sorted(
                scored, key=lambda s: s.spec.cost_per_1k
            )
            # 但也要保证能力匹配度不低于 0.5
            for sm in sorted_by_cost:
                if sm.breakdown.get("capability_match", 0) >= 0.5:
                    return sm
            return sorted_by_cost[0]

        if self._strategy == RouterStrategy.LOCAL_FIRST:
            for sm in scored:
                if sm.spec.is_local:
                    return sm
            return scored[0]

        if self._strategy == RouterStrategy.PERFORMANCE_FIRST:
            sorted_by_latency = sorted(scored, key=lambda s: s.spec.avg_latency_ms)
            return sorted_by_latency[0]

        # 默认：CAPABILITY_FIRST，直接用评分最高
        return scored[0]

    def _estimate_cost(self, model: ModelSpec, estimated_tokens: int = 2000) -> float:
        """估算单次调用成本"""
        if model.is_local:
            return 0.0
        prompt_tokens = estimated_tokens * 0.6
        completion_tokens = estimated_tokens * 0.4
        return round(
            prompt_tokens / 1000 * model.cost_per_1k_prompt
            + completion_tokens / 1000 * model.cost_per_1k_completion,
            6,
        )

    def _estimate_tokens(self, tier: ComplexityTier) -> int:
        """按复杂度估算 token 用量"""
        if tier == ComplexityTier.SIMPLE:
            return 1000
        elif tier == ComplexityTier.MODERATE:
            return 3000
        else:
            return 8000

    def _build_reason(
        self, best: ScoredModel, tier: ComplexityTier, required: set[ModelCapability]
    ) -> str:
        parts = [f"复杂度={tier.value}"]

        if required:
            cap_names = [c.value for c in required]
            parts.append(f"能力={cap_names}")
            match_pct = best.breakdown.get("capability_match", 0) * 100
            parts.append(f"匹配度={match_pct:.0f}%")

        parts.append(f"评分={best.score:.2f}")
        parts.append(f"成本={best.spec.cost_per_1k:.6f}/1K tokens")

        if best.spec.is_local:
            parts.append("(本地/免费)")

        return ", ".join(parts)

    # ── 统计 ──

    @property
    def stats(self) -> dict:
        return {
            "routing_count": dict(self._routing_count),
            "fallback_count": self._fallback_count,
            "total_routes": sum(self._routing_count.values()),
            "strategy": self._strategy,
        }

    def get_top_routed(self, n: int = 5) -> list[tuple[str, int]]:
        """获取最常被路由的模型 Top-N"""
        sorted_models = sorted(
            self._routing_count.items(), key=lambda x: x[1], reverse=True
        )
        return sorted_models[:n]


# ── 全局单例 ──
default_router = ModelRouter()
