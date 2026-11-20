"""
Model Router — 数据模型

定义模型规格、路由决策、复杂度等级、能力常量。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ── 能力常量 ─────────────────────────────────────────────────

class ModelCapability(str, enum.Enum):
    """模型能力标签（区别于 Scheduler 的 Worker Capability）"""
    CODE_GENERATION = "code_generation"
    ARCHITECTURE_DESIGN = "architecture_design"
    DATA_ANALYSIS = "data_analysis"
    TEXT_GENERATION = "text_generation"
    SUMMARIZATION = "summarization"
    TRANSLATION = "translation"
    REASONING = "reasoning"
    TOOL_USE = "tool_use"
    MULTI_MODAL = "multi_modal"
    LONG_CONTEXT = "long_context"
    FAST_RESPONSE = "fast_response"
    COST_EFFICIENT = "cost_efficient"


# ── 复杂度等级 ───────────────────────────────────────────────

class ComplexityTier(str, enum.Enum):
    """任务复杂度等级"""
    SIMPLE = "simple"       # 1-3，简单问答/摘要/翻译
    MODERATE = "moderate"   # 4-6，中等分析/中等代码
    COMPLEX = "complex"     # 7-10，架构设计/复杂推理/长代码


def complexity_from_score(score: int) -> ComplexityTier:
    """从数值转为复杂度等级"""
    if score <= 3:
        return ComplexityTier.SIMPLE
    elif score <= 6:
        return ComplexityTier.MODERATE
    else:
        return ComplexityTier.COMPLEX


# ── 模型规格 ─────────────────────────────────────────────────

@dataclass
class ModelSpec:
    """LLM 模型规格"""
    name: str                           # 如 "gpt-4o", "qwen2.5"
    provider: str                       # "openai" | "anthropic" | "ollama" | "mock"
    capabilities: set[ModelCapability] = field(default_factory=set)
    complexity_tier: ComplexityTier = ComplexityTier.MODERATE
    context_window: int = 128000
    cost_per_1k_prompt: float = 0.0     # USD / 1K tokens
    cost_per_1k_completion: float = 0.0
    avg_latency_ms: int = 2000          # 平均延迟
    available: bool = True              # 是否可用
    priority: int = 0                   # 同分时的优先级（越高越优先）
    tags: list[str] = field(default_factory=list)

    @property
    def cost_per_1k(self) -> float:
        """综合单位成本（prompt + completion 平均）"""
        return (self.cost_per_1k_prompt + self.cost_per_1k_completion) / 2

    @property
    def is_local(self) -> bool:
        return self.provider == "ollama"

    @property
    def is_cloud(self) -> bool:
        return not self.is_local


# ── 路由决策 ─────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    """路由决策结果"""
    model: ModelSpec
    reason: str = ""
    alternatives: list[ModelSpec] = field(default_factory=list)  # 备选模型
    estimated_cost: float = 0.0
    estimated_tokens: int = 0
    fallback_used: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model.name,
            "provider": self.model.provider,
            "reason": self.reason,
            "alternatives": [m.name for m in self.alternatives],
            "estimated_cost": self.estimated_cost,
            "estimated_tokens": self.estimated_tokens,
            "fallback_used": self.fallback_used,
        }
