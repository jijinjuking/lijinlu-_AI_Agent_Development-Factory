"""
Model Scoring — 模型评分引擎

多维评分：能力匹配 + 成本 + 延迟 + 复杂度适配。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.runtime.model_router.models import (
    ModelSpec, ModelCapability, ComplexityTier,
)


@dataclass
class ScoredModel:
    """带评分的模型"""
    spec: ModelSpec
    score: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"ScoredModel({self.spec.name}, score={self.score:.2f})"


class ModelScorer:
    """
    模型评分器。

    评分维度（总计最高 1.0）：
    - capability_match: 0.40 — 能力匹配度
    - cost_efficiency:  0.25 — 成本效率
    - latency:          0.15 — 延迟表现
    - tier_fit:         0.10 — 复杂度适配
    - priority:         0.10 — 模型优先级
    """

    WEIGHTS = {
        "capability_match": 0.40,
        "cost_efficiency": 0.25,
        "latency": 0.15,
        "tier_fit": 0.10,
        "priority": 0.10,
    }

    def __init__(self, weights: dict[str, float] | None = None):
        if weights:
            self._weights = weights
        else:
            self._weights = dict(self.WEIGHTS)

    def score(
        self,
        candidates: list[ModelSpec],
        required_capabilities: set[ModelCapability] | None = None,
        target_tier: ComplexityTier | None = None,
        prefer_local: bool = False,
    ) -> list[ScoredModel]:
        """
        对候选模型打分排序。

        Args:
            candidates: 候选模型列表
            required_capabilities: 必需的能力集合
            target_tier: 目标复杂度等级
            prefer_local: 是否偏好本地模型（隐私优先）

        Returns:
            按分数降序排列的评分结果
        """
        scored = []

        # 如果无候选，返回空
        if not candidates:
            return scored

        # 提取各维度的极值用于归一化
        max_latency = max(m.avg_latency_ms for m in candidates) or 1
        max_cost = max(m.cost_per_1k for m in candidates) or 0.001
        # 成本归一化的最小值（避免除零）
        min_cost = min(m.cost_per_1k for m in candidates) or 0.0
        cost_range = max_cost - min_cost or 0.001

        required = required_capabilities or set()

        for model in candidates:
            breakdown: dict[str, float] = {}
            total = 0.0

            # 1. 能力匹配度 (0.40)
            cap_score = self._capability_match(model, required)
            breakdown["capability_match"] = cap_score
            total += cap_score * self._weights["capability_match"]

            # 2. 成本效率 (0.25)
            # 归一化：成本越低分数越高
            if model.is_local:
                cost_score = 1.0  # 本地免费模型满分
            else:
                cost_score = 1.0 - (model.cost_per_1k - min_cost) / cost_range
                cost_score = max(0.0, min(1.0, cost_score))
            breakdown["cost_efficiency"] = cost_score
            total += cost_score * self._weights["cost_efficiency"]

            # 3. 延迟 (0.15)
            latency_score = 1.0 - (model.avg_latency_ms / max_latency)
            latency_score = max(0.0, min(1.0, latency_score))
            breakdown["latency"] = latency_score
            total += latency_score * self._weights["latency"]

            # 4. 复杂度适配 (0.10)
            tier_score = self._tier_fit(model, target_tier)
            breakdown["tier_fit"] = tier_score
            total += tier_score * self._weights["tier_fit"]

            # 5. 优先级 (0.10)
            # 归一化到 0-1，最高优先级 10
            priority_score = model.priority / 10.0
            breakdown["priority"] = priority_score
            total += priority_score * self._weights["priority"]

            # 6. 本地偏好加成
            if prefer_local and model.is_local:
                total += 0.05  # 微小的本地加成

            scored.append(ScoredModel(spec=model, score=total, breakdown=breakdown))

        # 按分数降序排列
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored

    def _capability_match(
        self, model: ModelSpec, required: set[ModelCapability]
    ) -> float:
        """计算能力匹配度"""
        if not required:
            return 1.0  # 没有要求时满分
        matched = len(required & model.capabilities)
        return matched / len(required)

    def _tier_fit(
        self, model: ModelSpec, target_tier: ComplexityTier | None
    ) -> float:
        """计算复杂度适配度"""
        if target_tier is None:
            return 0.5  # 无目标时中性分

        # 完全匹配 → 1.0
        if model.complexity_tier == target_tier:
            return 1.0

        # 高配模型处理低复杂度任务 → 0.7（能用但贵）
        if (model.complexity_tier == ComplexityTier.COMPLEX
                and target_tier == ComplexityTier.MODERATE):
            return 0.7
        if (model.complexity_tier == ComplexityTier.COMPLEX
                and target_tier == ComplexityTier.SIMPLE):
            return 0.4
        if (model.complexity_tier == ComplexityTier.MODERATE
                and target_tier == ComplexityTier.SIMPLE):
            return 0.7

        # 低配模型处理高复杂度任务 → 0.3（能力可能不足）
        if (model.complexity_tier == ComplexityTier.SIMPLE
                and target_tier == ComplexityTier.COMPLEX):
            return 0.2
        if (model.complexity_tier == ComplexityTier.MODERATE
                and target_tier == ComplexityTier.COMPLEX):
            return 0.4
        if (model.complexity_tier == ComplexityTier.SIMPLE
                and target_tier == ComplexityTier.MODERATE):
            return 0.4

        return 0.5


# ── 全局单例 ──
default_scorer = ModelScorer()
