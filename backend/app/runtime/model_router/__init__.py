"""
Model Router (W11) — 动态模型路由

"简单任务用小模型，复杂任务用大模型"

组件:
- ModelSpec: 模型规格（能力、复杂度等级、成本、延迟）
- ModelRegistry: 模型注册中心（预配置 10+ 主流模型）
- ModelScorer: 多维评分引擎（能力匹配 + 成本 + 延迟 + 适配度）
- ModelRouter: 核心路由器（能力路由 + 复杂度路由 + 成本优化 + 回退链）
"""
from app.runtime.model_router.models import (
    ModelSpec,
    ModelCapability,
    ComplexityTier,
    RoutingDecision,
    complexity_from_score,
)
from app.runtime.model_router.model_registry import (
    ModelRegistry,
    PRESET_MODELS,
    model_registry,
)
from app.runtime.model_router.scoring import (
    ModelScorer,
    ScoredModel,
    default_scorer,
)
from app.runtime.model_router.router import (
    ModelRouter,
    RouterStrategy,
    default_router,
)

__all__ = [
    "ModelSpec",
    "ModelCapability",
    "ComplexityTier",
    "RoutingDecision",
    "complexity_from_score",
    "ModelRegistry",
    "PRESET_MODELS",
    "model_registry",
    "ModelScorer",
    "ScoredModel",
    "default_scorer",
    "ModelRouter",
    "RouterStrategy",
    "default_router",
]
