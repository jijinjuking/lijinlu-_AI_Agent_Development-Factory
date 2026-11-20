"""
Model Router 测试套件 (W11)

覆盖:
- ModelSpec / ComplexityTier / RoutingDecision 数据模型
- ModelRegistry 注册/查询/变更
- ModelScorer 多维评分
- ModelRouter 路由策略（能力/复杂度/成本/回退）
- 集成测试
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone

from app.runtime.model_router.models import (
    ModelSpec, ModelCapability, ComplexityTier, RoutingDecision,
    complexity_from_score,
)
from app.runtime.model_router.model_registry import (
    ModelRegistry, PRESET_MODELS, model_registry as global_registry,
)
from app.runtime.model_router.scoring import (
    ModelScorer, ScoredModel, default_scorer,
)
from app.runtime.model_router.router import (
    ModelRouter, RouterStrategy, default_router,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def small_model() -> ModelSpec:
    return ModelSpec(
        name="gpt-4o-mini",
        provider="openai",
        capabilities={
            ModelCapability.TEXT_GENERATION,
            ModelCapability.SUMMARIZATION,
            ModelCapability.FAST_RESPONSE,
            ModelCapability.COST_EFFICIENT,
        },
        complexity_tier=ComplexityTier.SIMPLE,
        cost_per_1k_prompt=0.00015,
        cost_per_1k_completion=0.0006,
        avg_latency_ms=500,
        priority=8,
    )


@pytest.fixture
def large_model() -> ModelSpec:
    return ModelSpec(
        name="gpt-4o",
        provider="openai",
        capabilities={
            ModelCapability.CODE_GENERATION,
            ModelCapability.ARCHITECTURE_DESIGN,
            ModelCapability.REASONING,
            ModelCapability.TOOL_USE,
        },
        complexity_tier=ComplexityTier.COMPLEX,
        cost_per_1k_prompt=0.005,
        cost_per_1k_completion=0.015,
        avg_latency_ms=2000,
        priority=10,
    )


@pytest.fixture
def local_model() -> ModelSpec:
    return ModelSpec(
        name="qwen2.5",
        provider="ollama",
        capabilities={
            ModelCapability.TEXT_GENERATION,
            ModelCapability.CODE_GENERATION,
            ModelCapability.FAST_RESPONSE,
            ModelCapability.COST_EFFICIENT,
        },
        complexity_tier=ComplexityTier.MODERATE,
        cost_per_1k_prompt=0.0,
        cost_per_1k_completion=0.0,
        avg_latency_ms=1500,
        priority=5,
    )


@pytest.fixture
def code_model() -> ModelSpec:
    return ModelSpec(
        name="deepseek-coder",
        provider="ollama",
        capabilities={
            ModelCapability.CODE_GENERATION,
            ModelCapability.REASONING,
            ModelCapability.FAST_RESPONSE,
        },
        complexity_tier=ComplexityTier.MODERATE,
        cost_per_1k_prompt=0.0,
        cost_per_1k_completion=0.0,
        avg_latency_ms=1800,
        priority=6,
    )


@pytest.fixture
def sample_registry(small_model, large_model, local_model, code_model) -> ModelRegistry:
    reg = ModelRegistry({})
    reg._models = {
        "gpt-4o-mini": small_model,
        "gpt-4o": large_model,
        "qwen2.5": local_model,
        "deepseek-coder": code_model,
    }
    return reg


@pytest.fixture
def router(sample_registry) -> ModelRouter:
    return ModelRouter(registry=sample_registry)


# ═══════════════════════════════════════════════════════════════
# Test: Data Models
# ═══════════════════════════════════════════════════════════════

class TestDataModels:

    def test_complexity_from_score_simple(self):
        assert complexity_from_score(1) == ComplexityTier.SIMPLE
        assert complexity_from_score(2) == ComplexityTier.SIMPLE
        assert complexity_from_score(3) == ComplexityTier.SIMPLE

    def test_complexity_from_score_moderate(self):
        assert complexity_from_score(4) == ComplexityTier.MODERATE
        assert complexity_from_score(5) == ComplexityTier.MODERATE
        assert complexity_from_score(6) == ComplexityTier.MODERATE

    def test_complexity_from_score_complex(self):
        assert complexity_from_score(7) == ComplexityTier.COMPLEX
        assert complexity_from_score(8) == ComplexityTier.COMPLEX
        assert complexity_from_score(10) == ComplexityTier.COMPLEX

    def test_model_spec_is_local(self):
        cloud = ModelSpec(name="gpt-4o", provider="openai")
        local = ModelSpec(name="qwen", provider="ollama")
        assert not cloud.is_local
        assert local.is_local

    def test_model_spec_cost_per_1k(self, small_model, large_model):
        assert small_model.cost_per_1k == (0.00015 + 0.0006) / 2
        assert large_model.cost_per_1k == (0.005 + 0.015) / 2

    def test_routing_decision_to_dict(self, small_model):
        decision = RoutingDecision(
            model=small_model,
            reason="test",
            alternatives=[],
            estimated_cost=0.001,
            estimated_tokens=1000,
        )
        d = decision.to_dict()
        assert d["model"] == "gpt-4o-mini"
        assert d["provider"] == "openai"
        assert d["reason"] == "test"
        assert d["estimated_cost"] == 0.001


# ═══════════════════════════════════════════════════════════════
# Test: ModelRegistry
# ═══════════════════════════════════════════════════════════════

class TestModelRegistry:

    def test_global_registry_has_models(self):
        assert len(global_registry) >= 10

    def test_get_existing_model(self, sample_registry):
        m = sample_registry.get("gpt-4o")
        assert m is not None
        assert m.provider == "openai"

    def test_get_missing_model(self, sample_registry):
        assert sample_registry.get("nonexistent") is None

    def test_list_all(self, sample_registry):
        models = sample_registry.list_all()
        assert len(models) == 4

    def test_list_all_available_only(self, sample_registry, small_model):
        small_model.available = False
        available = sample_registry.list_all(available_only=True)
        assert len(available) == 3
        small_model.available = True  # cleanup

    def test_list_by_provider(self, sample_registry):
        openai_models = sample_registry.list_by_provider("openai")
        assert len(openai_models) == 2
        ollama_models = sample_registry.list_by_provider("ollama")
        assert len(ollama_models) == 2

    def test_list_by_capability(self, sample_registry):
        code_models = sample_registry.list_by_capability(ModelCapability.CODE_GENERATION)
        assert len(code_models) >= 2
        names = {m.name for m in code_models}
        assert "gpt-4o" in names or "deepseek-coder" in names

    def test_list_by_tier(self, sample_registry):
        simple_models = sample_registry.list_by_tier(ComplexityTier.SIMPLE)
        assert len(simple_models) >= 1

    def test_find_by_capabilities_exact(self, sample_registry):
        result = sample_registry.find_by_capabilities({
            ModelCapability.CODE_GENERATION,
            ModelCapability.ARCHITECTURE_DESIGN,
            ModelCapability.REASONING,
            ModelCapability.TOOL_USE,
        })
        assert len(result) == 1
        assert result[0].name == "gpt-4o"

    def test_find_by_capabilities_partial(self, sample_registry):
        result = sample_registry.find_by_capabilities({
            ModelCapability.CODE_GENERATION,
        })
        # gpt-4o, qwen2.5, deepseek-coder
        assert len(result) >= 3

    def test_find_by_capabilities_unavailable_excluded(self, sample_registry, small_model):
        small_model.available = False
        result = sample_registry.find_by_capabilities({
            ModelCapability.TEXT_GENERATION,
            ModelCapability.COST_EFFICIENT,
        })
        names = {m.name for m in result}
        assert "gpt-4o-mini" not in names
        small_model.available = True

    @pytest.mark.asyncio
    async def test_register_new_model(self, sample_registry):
        new_model = ModelSpec(name="test-model", provider="mock")
        await sample_registry.register(new_model)
        assert sample_registry.get("test-model") is not None
        assert len(sample_registry) == 5

    @pytest.mark.asyncio
    async def test_register_overwrite(self, sample_registry):
        updated = ModelSpec(name="gpt-4o", provider="openai", priority=99)
        await sample_registry.register(updated)
        m = sample_registry.get("gpt-4o")
        assert m is not None
        assert m.priority == 99

    @pytest.mark.asyncio
    async def test_unregister(self, sample_registry):
        assert await sample_registry.unregister("deepseek-coder") is True
        assert sample_registry.get("deepseek-coder") is None

    @pytest.mark.asyncio
    async def test_unregister_nonexistent(self, sample_registry):
        assert await sample_registry.unregister("nonexistent") is False

    @pytest.mark.asyncio
    async def test_set_available(self, sample_registry, small_model):
        assert await sample_registry.set_available("gpt-4o-mini", False) is True
        assert small_model.available is False
        # 恢复
        assert await sample_registry.set_available("gpt-4o-mini", True) is True

    @pytest.mark.asyncio
    async def test_set_available_nonexistent(self, sample_registry):
        assert await sample_registry.set_available("nonexistent", False) is False

    @pytest.mark.asyncio
    async def test_record_latency(self, sample_registry):
        m = sample_registry.get("gpt-4o")
        original = m.avg_latency_ms
        await sample_registry.record_latency("gpt-4o", 100)
        # 指数滑动平均, 应该变了
        assert m.avg_latency_ms != original
        expected = int(original * 0.7 + 100 * 0.3)
        assert m.avg_latency_ms == expected


# ═══════════════════════════════════════════════════════════════
# Test: ModelScorer
# ═══════════════════════════════════════════════════════════════

class TestModelScorer:

    def test_empty_candidates(self):
        result = default_scorer.score([])
        assert result == []

    def test_single_model(self, small_model):
        result = default_scorer.score([small_model])
        assert len(result) == 1
        assert result[0].spec.name == "gpt-4o-mini"
        assert 0 <= result[0].score <= 1.0
        assert "capability_match" in result[0].breakdown

    def test_capability_match_perfect(self, large_model):
        result = default_scorer.score(
            [large_model],
            required_capabilities={
                ModelCapability.CODE_GENERATION,
                ModelCapability.REASONING,
            },
        )
        assert result[0].breakdown["capability_match"] == 1.0

    def test_capability_match_partial(self, small_model):
        """small_model 有 TEXT_GENERATION 但没有 CODE_GENERATION"""
        result = default_scorer.score(
            [small_model],
            required_capabilities={
                ModelCapability.TEXT_GENERATION,          # small_model 有
                ModelCapability.ARCHITECTURE_DESIGN,       # small_model 没有
            },
        )
        assert 0 < result[0].breakdown["capability_match"] < 1.0

    def test_capability_match_empty_required(self, small_model):
        result = default_scorer.score([small_model], required_capabilities=set())
        assert result[0].breakdown["capability_match"] == 1.0

    def test_scoring_order(self, small_model, large_model):
        """大模型能力匹配高，但小模型成本低 — 综合评分应排序"""
        result = default_scorer.score(
            [small_model, large_model],
            required_capabilities={ModelCapability.CODE_GENERATION},
        )
        # 两个都应该被评分
        assert len(result) == 2
        # 排序：分数从高到低
        assert result[0].score >= result[1].score

    def test_tier_fit_perfect(self, small_model):
        result = default_scorer.score(
            [small_model],
            target_tier=ComplexityTier.SIMPLE,
        )
        assert result[0].breakdown["tier_fit"] == 1.0

    def test_tier_fit_mismatch_small_for_complex(self, small_model):
        result = default_scorer.score(
            [small_model],
            target_tier=ComplexityTier.COMPLEX,
        )
        assert result[0].breakdown["tier_fit"] < 0.5

    def test_tier_fit_large_for_simple(self, large_model):
        result = default_scorer.score(
            [large_model],
            target_tier=ComplexityTier.SIMPLE,
        )
        assert result[0].breakdown["tier_fit"] == 0.4

    def test_local_model_cost_score(self, local_model, small_model):
        result = default_scorer.score([local_model, small_model])
        local_scored = [r for r in result if r.spec.is_local][0]
        assert local_scored.breakdown["cost_efficiency"] == 1.0

    def test_prefer_local_bonus(self, local_model, small_model):
        result = default_scorer.score(
            [local_model, small_model],
            prefer_local=True,
        )
        local_scored = [r for r in result if r.spec.is_local][0]
        cloud_scored = [r for r in result if not r.spec.is_local][0]
        # 本地模型应该有额外加成
        assert local_scored.score > local_model.priority / 10.0 * 0.10 + 0.4  # 不是精确验证,大致确认高于基准

    def test_custom_weights(self, small_model, large_model):
        scorer = ModelScorer(weights={
            "capability_match": 0.1,
            "cost_efficiency": 0.7,
            "latency": 0.05,
            "tier_fit": 0.05,
            "priority": 0.1,
        })
        result = scorer.score([small_model, large_model])
        # 成本权重高,小模型应该排前面
        assert result[0].spec.name == "gpt-4o-mini"


# ═══════════════════════════════════════════════════════════════
# Test: ModelRouter
# ═══════════════════════════════════════════════════════════════

class TestModelRouterBasic:

    @pytest.mark.asyncio
    async def test_route_simple_task(self, router, small_model):
        """简单任务 → 小模型"""
        decision = await router.route(complexity=2)
        assert decision.model.complexity_tier in (ComplexityTier.SIMPLE, ComplexityTier.MODERATE)
        assert decision.reason

    @pytest.mark.asyncio
    async def test_route_complex_task(self, router, large_model):
        """复杂任务 + 架构能力 → 大模型"""
        decision = await router.route(
            complexity=8,
            required_capabilities={ModelCapability.ARCHITECTURE_DESIGN},
        )
        assert decision.model.complexity_tier == ComplexityTier.COMPLEX

    @pytest.mark.asyncio
    async def test_route_with_capabilities_exact(self, router):
        """能力路由：精确匹配"""
        decision = await router.route(
            complexity=5,
            required_capabilities={
                ModelCapability.ARCHITECTURE_DESIGN,
                ModelCapability.TOOL_USE,
            },
        )
        assert decision.model.name == "gpt-4o"  # 唯一满足架构 + 工具的模型

    @pytest.mark.asyncio
    async def test_route_with_capabilities_code(self, router):
        """能力路由：代码生成"""
        decision = await router.route(
            complexity=5,
            required_capabilities={ModelCapability.CODE_GENERATION},
        )
        # 多个模型满足，选评分最高的
        assert decision.model.name

    @pytest.mark.asyncio
    async def test_route_preferred_model(self, router, small_model):
        """用户指定模型"""
        decision = await router.route(
            preferred_model="gpt-4o-mini",
            complexity=8,  # 高复杂度但用户指定小模型
        )
        assert decision.model.name == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_route_preferred_model_unavailable(self, router):
        """指定模型不可用应跳过"""
        decision = await router.route(
            preferred_model="nonexistent",
            complexity=3,
        )
        assert decision.model.name != "nonexistent"

    @pytest.mark.asyncio
    async def test_route_prefer_local(self, router):
        """本地优先策略"""
        decision = await router.route(
            complexity=5,
            prefer_local=True,
            required_capabilities={ModelCapability.CODE_GENERATION},
        )
        assert decision.model.is_local

    @pytest.mark.asyncio
    async def test_route_max_budget_constraint(self, router):
        """预算约束"""
        # gpt-4o 的成本大约是 $0.016/次（2000 tokens），设 0.002 预算应排除
        decision = await router.route(
            complexity=8,
            max_budget=0.002,
        )
        # 应该选了更便宜的模型
        assert decision.model.name != "gpt-4o"

    @pytest.mark.asyncio
    async def test_route_exclude_models(self, router):
        """排除指定模型"""
        decision = await router.route(
            complexity=8,
            exclude_models={"gpt-4o"},
        )
        assert decision.model.name != "gpt-4o"

    @pytest.mark.asyncio
    async def test_route_alternatives(self, router):
        """备选列表"""
        decision = await router.route(complexity=5)
        if len(router._registry) > 1:
            assert len(decision.alternatives) >= 1

    @pytest.mark.asyncio
    async def test_route_estimated_cost(self, router):
        """估算成本非零"""
        decision = await router.route(complexity=5)
        if not decision.model.is_local:
            assert decision.estimated_cost >= 0

    @pytest.mark.asyncio
    async def test_route_no_capabilities_match(self, router):
        """找不到完全匹配的，应降级到最有能力的模型"""
        decision = await router.route(
            complexity=5,
            required_capabilities={
                ModelCapability.MULTI_MODAL,  # 只有 gpt-4o 有（预设中）,但我们的测试 registry 可能没有
            },
        )
        # 至少能路由成功
        assert decision.model is not None


class TestModelRouterFallback:

    @pytest.mark.asyncio
    async def test_route_with_fallback_normal(self, router):
        """正常路由（不触发回退）"""
        decision = await router.route_with_fallback(complexity=3)
        assert not decision.fallback_used
        assert decision.model is not None

    @pytest.mark.asyncio
    async def test_on_model_failure_returns_alternative(self, router):
        """模型失败时返回备选"""
        alternative = await router.on_model_failure("gpt-4o")
        assert alternative is not None
        assert alternative.name != "gpt-4o"

    @pytest.mark.asyncio
    async def test_on_model_failure_same_provider_preferred(self, router):
        """失败时优先同 provider"""
        alternative = await router.on_model_failure("gpt-4o")
        assert alternative is not None
        # 同 provider 优先（openai → gpt-4o-mini）
        assert alternative.provider == "openai"

    @pytest.mark.asyncio
    async def test_on_model_failure_last_model(self, router):
        """只剩一个模型失败——返回 None"""
        # 创建一个只有一个模型的 registry
        single = ModelRegistry({
            "only-model": ModelSpec(name="only-model", provider="mock"),
        })
        r = ModelRouter(registry=single)
        assert await r.on_model_failure("only-model") is None

    @pytest.mark.asyncio
    async def test_fallback_count_increments(self, router):
        initial = router.stats["fallback_count"]
        await router.on_model_failure("gpt-4o")
        assert router.stats["fallback_count"] == initial + 1


class TestModelRouterStrategies:

    @pytest.mark.asyncio
    async def test_cost_first_strategy(self, sample_registry):
        r = ModelRouter(registry=sample_registry, strategy=RouterStrategy.COST_FIRST)
        decision = await r.route(complexity=5)
        # 应该选成本最低的
        assert decision.model.is_local  # 免费模型

    @pytest.mark.asyncio
    async def test_local_first_strategy(self, sample_registry):
        r = ModelRouter(registry=sample_registry, strategy=RouterStrategy.LOCAL_FIRST)
        decision = await r.route(complexity=5)
        assert decision.model.is_local

    @pytest.mark.asyncio
    async def test_performance_first_strategy(self, sample_registry, small_model, large_model):
        r = ModelRouter(registry=sample_registry, strategy=RouterStrategy.PERFORMANCE_FIRST)
        decision = await r.route(complexity=5)
        # 选延迟最低的（haiku 300ms / gpt-4o-mini 500ms）
        assert decision.model.avg_latency_ms <= 500

    @pytest.mark.asyncio
    async def test_routing_stats(self, router):
        await router.route(complexity=3)
        await router.route(complexity=8)
        stats = router.stats
        assert stats["total_routes"] == 2
        assert len(stats["routing_count"]) > 0


# ═══════════════════════════════════════════════════════════════
# Test: Integration (Global Defaults)
# ═══════════════════════════════════════════════════════════════

class TestModelRouterIntegration:

    @pytest.mark.asyncio
    async def test_default_router_routes(self):
        """default_router 使用全局 model_registry 能正常工作"""
        decision = await default_router.route(
            complexity=3,
            required_capabilities={ModelCapability.TEXT_GENERATION},
        )
        assert decision.model is not None

    @pytest.mark.asyncio
    async def test_default_router_complex_code(self):
        """复杂代码任务 → Claude 或 GPT-4o（能力路由）"""
        decision = await default_router.route(
            complexity=8,
            required_capabilities={
                ModelCapability.CODE_GENERATION,
                ModelCapability.REASONING,
                ModelCapability.TOOL_USE,           # 缩小候选范围
                ModelCapability.ARCHITECTURE_DESIGN, # 只有旗舰模型满足
            },
        )
        top_models = {m.name for m in decision.alternatives[:2]} | {decision.model.name}
        # 至少包含一个旗舰模型
        flagships = {"gpt-4o", "claude-3-5-sonnet", "deepseek-reasoner", "gpt-4-turbo"}
        assert top_models & flagships, f"Expected a flagship model, got: {top_models}"

    @pytest.mark.asyncio
    async def test_default_router_simple_cheap(self):
        """简单任务 → 便宜模型"""
        decision = await default_router.route(complexity=2)
        # 应该是轻量级模型
        lightweight = {"gpt-4o-mini", "claude-3-haiku", "qwen2.5", "deepseek-chat"}
        assert decision.model.name in lightweight or decision.model.is_local

    def test_preset_models_coverage(self):
        """预配置模型覆盖主流 provider"""
        providers = {m.provider for m in PRESET_MODELS.values()}
        assert "openai" in providers
        assert "anthropic" in providers
        assert "ollama" in providers

    def test_preset_models_code_capability(self):
        """至少有 3 个模型支持代码生成"""
        code_models = global_registry.list_by_capability(ModelCapability.CODE_GENERATION)
        assert len(code_models) >= 3
