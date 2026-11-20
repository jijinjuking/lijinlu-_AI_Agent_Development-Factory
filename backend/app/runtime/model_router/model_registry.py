"""
Model Registry — 模型注册中心

预配置主流模型 + 动态注册/注销能力。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from app.runtime.model_router.models import (
    ModelSpec, ModelCapability, ComplexityTier,
)


# ── 预设模型 ──────────────────────────────────────────────────
# 定价数据与 policy_engine 中的 MODEL_PRICING 对齐

PRESET_MODELS: dict[str, ModelSpec] = {
    # ── OpenAI ──
    "gpt-4o": ModelSpec(
        name="gpt-4o",
        provider="openai",
        capabilities={
            ModelCapability.CODE_GENERATION,
            ModelCapability.ARCHITECTURE_DESIGN,
            ModelCapability.DATA_ANALYSIS,
            ModelCapability.TEXT_GENERATION,
            ModelCapability.REASONING,
            ModelCapability.TOOL_USE,
            ModelCapability.MULTI_MODAL,
            ModelCapability.LONG_CONTEXT,
        },
        complexity_tier=ComplexityTier.COMPLEX,
        context_window=128000,
        cost_per_1k_prompt=0.005,
        cost_per_1k_completion=0.015,
        avg_latency_ms=2000,
        priority=10,
        tags=["flagship", "multimodal"],
    ),
    "gpt-4o-mini": ModelSpec(
        name="gpt-4o-mini",
        provider="openai",
        capabilities={
            ModelCapability.TEXT_GENERATION,
            ModelCapability.SUMMARIZATION,
            ModelCapability.TRANSLATION,
            ModelCapability.FAST_RESPONSE,
            ModelCapability.COST_EFFICIENT,
            ModelCapability.CODE_GENERATION,
        },
        complexity_tier=ComplexityTier.SIMPLE,
        context_window=128000,
        cost_per_1k_prompt=0.00015,
        cost_per_1k_completion=0.0006,
        avg_latency_ms=500,
        priority=8,
        tags=["lightweight", "cost-efficient"],
    ),
    "gpt-4-turbo": ModelSpec(
        name="gpt-4-turbo",
        provider="openai",
        capabilities={
            ModelCapability.CODE_GENERATION,
            ModelCapability.ARCHITECTURE_DESIGN,
            ModelCapability.REASONING,
            ModelCapability.DATA_ANALYSIS,
            ModelCapability.TEXT_GENERATION,
            ModelCapability.TOOL_USE,
        },
        complexity_tier=ComplexityTier.COMPLEX,
        context_window=128000,
        cost_per_1k_prompt=0.01,
        cost_per_1k_completion=0.03,
        avg_latency_ms=2500,
        priority=9,
        tags=["flagship", "legacy"],
    ),

    # ── Anthropic ──
    "claude-3-5-sonnet": ModelSpec(
        name="claude-3-5-sonnet",
        provider="anthropic",
        capabilities={
            ModelCapability.CODE_GENERATION,
            ModelCapability.ARCHITECTURE_DESIGN,
            ModelCapability.DATA_ANALYSIS,
            ModelCapability.TEXT_GENERATION,
            ModelCapability.REASONING,
            ModelCapability.TOOL_USE,
            ModelCapability.LONG_CONTEXT,
        },
        complexity_tier=ComplexityTier.COMPLEX,
        context_window=200000,
        cost_per_1k_prompt=0.003,
        cost_per_1k_completion=0.015,
        avg_latency_ms=3000,
        priority=10,
        tags=["code", "architecture", "flagship"],
    ),
    "claude-3-haiku": ModelSpec(
        name="claude-3-haiku",
        provider="anthropic",
        capabilities={
            ModelCapability.TEXT_GENERATION,
            ModelCapability.SUMMARIZATION,
            ModelCapability.TRANSLATION,
            ModelCapability.FAST_RESPONSE,
            ModelCapability.COST_EFFICIENT,
            ModelCapability.CODE_GENERATION,
        },
        complexity_tier=ComplexityTier.SIMPLE,
        context_window=200000,
        cost_per_1k_prompt=0.00025,
        cost_per_1k_completion=0.00125,
        avg_latency_ms=300,
        priority=8,
        tags=["lightweight", "cost-efficient"],
    ),

    # ── Ollama（本地） ──
    "qwen2.5": ModelSpec(
        name="qwen2.5",
        provider="ollama",
        capabilities={
            ModelCapability.TEXT_GENERATION,
            ModelCapability.CODE_GENERATION,
            ModelCapability.SUMMARIZATION,
            ModelCapability.TRANSLATION,
            ModelCapability.REASONING,
            ModelCapability.FAST_RESPONSE,
            ModelCapability.COST_EFFICIENT,
        },
        complexity_tier=ComplexityTier.MODERATE,
        context_window=32768,
        cost_per_1k_prompt=0.0,
        cost_per_1k_completion=0.0,
        avg_latency_ms=1500,
        priority=5,
        tags=["local", "free", "privacy"],
    ),
    "llama3": ModelSpec(
        name="llama3",
        provider="ollama",
        capabilities={
            ModelCapability.TEXT_GENERATION,
            ModelCapability.CODE_GENERATION,
            ModelCapability.SUMMARIZATION,
            ModelCapability.TRANSLATION,
            ModelCapability.REASONING,
            ModelCapability.FAST_RESPONSE,
            ModelCapability.COST_EFFICIENT,
        },
        complexity_tier=ComplexityTier.MODERATE,
        context_window=8192,
        cost_per_1k_prompt=0.0,
        cost_per_1k_completion=0.0,
        avg_latency_ms=1200,
        priority=4,
        tags=["local", "free", "privacy"],
    ),
    "deepseek-coder": ModelSpec(
        name="deepseek-coder",
        provider="ollama",
        capabilities={
            ModelCapability.CODE_GENERATION,
            ModelCapability.REASONING,
            ModelCapability.FAST_RESPONSE,
            ModelCapability.COST_EFFICIENT,
        },
        complexity_tier=ComplexityTier.MODERATE,
        context_window=16384,
        cost_per_1k_prompt=0.0,
        cost_per_1k_completion=0.0,
        avg_latency_ms=1800,
        priority=6,
        tags=["local", "code", "free"],
    ),

    # ── DeepSeek（云端） ──
    "deepseek-chat": ModelSpec(
        name="deepseek-chat",
        provider="openai",  # DeepSeek 用 OpenAI 兼容 API
        capabilities={
            ModelCapability.TEXT_GENERATION,
            ModelCapability.CODE_GENERATION,
            ModelCapability.SUMMARIZATION,
            ModelCapability.TRANSLATION,
            ModelCapability.REASONING,
            ModelCapability.FAST_RESPONSE,
            ModelCapability.COST_EFFICIENT,
        },
        complexity_tier=ComplexityTier.MODERATE,
        context_window=128000,
        cost_per_1k_prompt=0.00014,
        cost_per_1k_completion=0.00028,
        avg_latency_ms=1000,
        priority=7,
        tags=["cost-efficient", "code"],
    ),
    "deepseek-reasoner": ModelSpec(
        name="deepseek-reasoner",
        provider="openai",
        capabilities={
            ModelCapability.REASONING,
            ModelCapability.ARCHITECTURE_DESIGN,
            ModelCapability.DATA_ANALYSIS,
            ModelCapability.CODE_GENERATION,
        },
        complexity_tier=ComplexityTier.COMPLEX,
        context_window=64000,
        cost_per_1k_prompt=0.00055,
        cost_per_1k_completion=0.00219,
        avg_latency_ms=5000,
        priority=8,
        tags=["reasoning", "deep-think"],
    ),
}


class ModelRegistry:
    """模型注册中心"""

    def __init__(self, models: dict[str, ModelSpec] | None = None):
        self._models: dict[str, ModelSpec] = dict(models or PRESET_MODELS)
        self._lock = asyncio.Lock()

    # ── 查询 ──

    def get(self, name: str) -> ModelSpec | None:
        """按名称获取模型"""
        return self._models.get(name)

    def list_all(self, available_only: bool = False) -> list[ModelSpec]:
        """列出全部模型"""
        models = list(self._models.values())
        if available_only:
            models = [m for m in models if m.available]
        return models

    def list_by_provider(self, provider: str) -> list[ModelSpec]:
        """按 provider 列出"""
        return [m for m in self._models.values() if m.provider == provider]

    def list_by_capability(self, capability: ModelCapability) -> list[ModelSpec]:
        """列出具有某项能力的模型"""
        return [m for m in self._models.values() if capability in m.capabilities]

    def list_by_tier(self, tier: ComplexityTier) -> list[ModelSpec]:
        """按复杂度等级列出"""
        return [m for m in self._models.values() if m.complexity_tier == tier]

    def find_by_capabilities(
        self, required: set[ModelCapability], available_only: bool = True
    ) -> list[ModelSpec]:
        """找出满足所有能力要求的模型"""
        candidates = [m for m in self._models.values() if required.issubset(m.capabilities)]
        if available_only:
            candidates = [m for m in candidates if m.available]
        return candidates

    # ── 变更 ──

    async def register(self, spec: ModelSpec) -> None:
        """注册/覆盖模型"""
        async with self._lock:
            self._models[spec.name] = spec

    async def unregister(self, name: str) -> bool:
        """注销模型"""
        async with self._lock:
            return self._models.pop(name, None) is not None

    async def set_available(self, name: str, available: bool) -> bool:
        """设置模型可用性"""
        async with self._lock:
            model = self._models.get(name)
            if model:
                model.available = available
                return True
            return False

    async def record_latency(self, name: str, latency_ms: int) -> None:
        """更新延迟统计（滑动平均）"""
        async with self._lock:
            model = self._models.get(name)
            if model:
                # 指数滑动平均 (alpha=0.3)
                model.avg_latency_ms = int(model.avg_latency_ms * 0.7 + latency_ms * 0.3)

    def __len__(self) -> int:
        return len(self._models)


# ── 全局单例 ──
model_registry = ModelRegistry()
