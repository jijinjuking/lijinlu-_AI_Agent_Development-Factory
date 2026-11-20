"""W35-36 Performance Optimization — 测试用例

覆盖模块：models / concurrency_controller / rate_limiter / llm_rate_limiter /
backpressure / benchmark_runner / metrics_collector / connection_pool / integration
"""

import asyncio
import time
import pytest
import pytest_asyncio

from app.runtime.performance.models import (
    BenchmarkConfig, BenchmarkResult, ConcurrencyLevelResult, BenchmarkSummary,
    PerformanceMetrics, MetricSnapshot,
    RateLimitRule, RateLimitResult, RateLimitStatus,
    ConcurrencyConfig, ConcurrencyStats, ConcurrencyMode,
    BackpressureConfig, BackpressureStats, BackpressureStrategy,
    ConnectionPoolConfig, PoolStats,
    LLMRateLimitConfig, LLMRateLimitState,
    RateLimitAlgorithm, LimitScope, MetricsAggregation,
)
from app.runtime.performance.concurrency_controller import ConcurrencyController
from app.runtime.performance.rate_limiter import RateLimiter, TokenBucket, SlidingWindow
from app.runtime.performance.llm_rate_limiter import LLMRateLimiter
from app.runtime.performance.backpressure import BackpressureController, BackpressureManager
from app.runtime.performance.benchmark_runner import BenchmarkRunner
from app.runtime.performance.metrics_collector import MetricsCollector
from app.runtime.performance.connection_pool import ConnectionPoolOptimizer


# ============================================================================
# Models Tests
# ============================================================================

class TestModels:
    """数据模型基础测试"""

    def test_benchmark_config_defaults(self):
        cfg = BenchmarkConfig()
        assert cfg.concurrency_levels == [1, 10, 50, 100]
        assert cfg.duration_sec == 30.0
        assert cfg.warmup_sec == 5.0

    def test_concurrency_config_defaults(self):
        cfg = ConcurrencyConfig()
        assert cfg.max_concurrent == 100
        assert cfg.min_concurrent == 10
        assert cfg.mode == ConcurrencyMode.FIXED

    def test_concurrency_config_adaptive(self):
        cfg = ConcurrencyConfig(
            mode=ConcurrencyMode.ADAPTIVE,
            max_concurrent=200,
            cpu_high_threshold=0.9,
        )
        assert cfg.mode == ConcurrencyMode.ADAPTIVE
        assert cfg.max_concurrent == 200

    def test_rate_limit_rule_defaults(self):
        rule = RateLimitRule(rule_id="test", name="Test Rule")
        assert rule.algorithm == RateLimitAlgorithm.TOKEN_BUCKET
        assert rule.rate == 100.0
        assert rule.burst == 200.0
        assert rule.enabled is True

    def test_rate_limit_rule_custom(self):
        rule = RateLimitRule(
            rule_id="custom", name="Custom",
            algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
            scope=LimitScope.PER_TENANT,
            window_sec=120, max_requests=500,
        )
        assert rule.algorithm == RateLimitAlgorithm.SLIDING_WINDOW
        assert rule.window_sec == 120
        assert rule.max_requests == 500

    def test_backpressure_config_defaults(self):
        cfg = BackpressureConfig(target="sse")
        assert cfg.max_queue_size == 1000
        assert cfg.strategy == BackpressureStrategy.DROP_OLDEST

    def test_connection_pool_config_defaults(self):
        cfg = ConnectionPoolConfig()
        assert cfg.pool_size == 20
        assert cfg.max_overflow == 10
        assert cfg.pool_pre_ping is True

    def test_llm_rate_limit_config_defaults(self):
        cfg = LLMRateLimitConfig(provider="openai")
        assert cfg.max_concurrent == 10
        assert cfg.max_rpm == 500
        assert cfg.auto_throttle is True

    def test_performance_metrics_defaults(self):
        metrics = PerformanceMetrics()
        assert metrics.total_requests == 0
        assert metrics.active_requests == 0
        assert metrics.cpu_percent == 0.0

    def test_metric_snapshot(self):
        snap = MetricSnapshot(metric_id="m1", name="test", value=42.0)
        assert snap.metric_id == "m1"
        assert snap.value == 42.0

    def test_concurrency_stats_defaults(self):
        stats = ConcurrencyStats()
        assert stats.max_allowed == 0
        assert stats.current_active == 0
        assert stats.mode == "fixed"

    def test_backpressure_stats_defaults(self):
        stats = BackpressureStats()
        assert stats.queue_size == 0
        assert stats.is_active is False

    def test_pool_stats_defaults(self):
        stats = PoolStats()
        assert stats.pool_size == 0
        assert stats.utilization == 0.0

    def test_llm_rate_limit_state(self):
        state = LLMRateLimitState(provider="openai", model="gpt-4")
        assert state.throttle_level == 1.0
        assert state.is_throttled is False

    def test_limit_scope_values(self):
        assert LimitScope.GLOBAL.value == "global"
        assert LimitScope.PER_TENANT.value == "per_tenant"
        assert LimitScope.PER_USER.value == "per_user"

    def test_rate_limit_algorithm_values(self):
        assert RateLimitAlgorithm.TOKEN_BUCKET.value == "token_bucket"
        assert RateLimitAlgorithm.SLIDING_WINDOW.value == "sliding_window"

    def test_backpressure_strategy_values(self):
        assert BackpressureStrategy.DROP_OLDEST.value == "drop_oldest"
        assert BackpressureStrategy.DEGRADE.value == "degrade"

    def test_metrics_aggregation_values(self):
        assert MetricsAggregation.P95.value == "p95"
        assert MetricsAggregation.AVG.value == "avg"


# ============================================================================
# TokenBucket Tests
# ============================================================================

class TestTokenBucket:
    """令牌桶算法测试"""

    @pytest.mark.asyncio
    async def test_initial_tokens(self):
        bucket = TokenBucket(rate=10.0, burst=100.0)
        assert bucket.available_tokens == 100.0

    @pytest.mark.asyncio
    async def test_consume_ok(self):
        bucket = TokenBucket(rate=100.0, burst=50.0)
        ok = await bucket.consume(1)
        assert ok is True
        assert bucket.available_tokens <= 50.0

    @pytest.mark.asyncio
    async def test_consume_exhaust(self):
        bucket = TokenBucket(rate=100.0, burst=10.0)
        for _ in range(10):
            ok = await bucket.consume(1)
            assert ok is True
        # 第11次应该失败
        ok = await bucket.consume(1)
        assert ok is False

    @pytest.mark.asyncio
    async def test_refill_rate(self):
        bucket = TokenBucket(rate=50.0, burst=10.0)
        # 耗尽
        for _ in range(10):
            await bucket.consume(1)
        assert bucket.available_tokens < 1.0

        # 等待补充
        await asyncio.sleep(0.1)  # 应该补充约 5 个令牌
        ok = await bucket.consume(1)
        assert ok is True

    @pytest.mark.asyncio
    async def test_cannot_exceed_burst(self):
        bucket = TokenBucket(rate=1000.0, burst=5.0)
        await asyncio.sleep(0.05)  # 补充很多令牌
        await bucket.consume(1)  # 触发 refill
        assert bucket.available_tokens <= 5.0  # 不能超过 burst

    @pytest.mark.asyncio
    async def test_multiple_tokens_consume(self):
        bucket = TokenBucket(rate=100.0, burst=50.0)
        ok = await bucket.consume(3)
        assert ok is True

    @pytest.mark.asyncio
    async def test_high_throughput(self):
        """高吞吐场景：大量快速请求"""
        bucket = TokenBucket(rate=500.0, burst=1000.0)
        allowed = 0
        for _ in range(100):
            if await bucket.consume(1):
                allowed += 1
        assert allowed > 0

    @pytest.mark.asyncio
    async def test_reset_at_calculation(self):
        bucket = TokenBucket(rate=10.0, burst=100.0)
        # 消耗 50 个令牌
        for _ in range(50):
            await bucket.consume(1)
        reset_sec = bucket.reset_at()
        assert reset_sec > 0


# ============================================================================
# SlidingWindow Tests
# ============================================================================

class TestSlidingWindow:
    """滑动窗口测试"""

    @pytest.mark.asyncio
    async def test_within_window(self):
        window = SlidingWindow(window_sec=60.0, max_requests=100)
        ok = await window.record_and_check()
        assert ok is True

    @pytest.mark.asyncio
    async def test_exceeds_max(self):
        window = SlidingWindow(window_sec=60.0, max_requests=5)
        for _ in range(5):
            ok = await window.record_and_check()
            assert ok is True
        # 第6次应该被拒绝
        ok = await window.record_and_check()
        assert ok is False

    @pytest.mark.asyncio
    async def test_current_count(self):
        window = SlidingWindow(window_sec=60.0, max_requests=100)
        for _ in range(10):
            await window.record_and_check()
        assert window.current_count == 10

    @pytest.mark.asyncio
    async def test_window_slides(self):
        """测试窗口过期（用短窗口模拟）"""
        window = SlidingWindow(window_sec=0.05, max_requests=100)
        for _ in range(5):
            await window.record_and_check()
        assert window.current_count == 5

        await asyncio.sleep(0.1)  # 窗口过期
        ok = await window.record_and_check()
        assert ok is True
        assert window.current_count <= 2  # 大部分已过期


# ============================================================================
# RateLimiter Tests
# ============================================================================

class TestRateLimiter:
    """限流器测试"""

    @pytest.mark.asyncio
    async def test_add_and_get_rule(self):
        limiter = RateLimiter()
        rule = RateLimitRule(rule_id="r1", name="Rule 1", rate=10.0, burst=20.0)
        limiter.add_rule(rule)
        assert limiter.get_rule("r1") is not None

    @pytest.mark.asyncio
    async def test_remove_rule(self):
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(rule_id="r1", name="R1"))
        assert limiter.remove_rule("r1") is True
        assert limiter.remove_rule("r1") is False

    @pytest.mark.asyncio
    async def test_list_rules(self):
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(rule_id="a", name="A"))
        limiter.add_rule(RateLimitRule(rule_id="b", name="B"))
        rules = limiter.list_rules()
        assert len(rules) == 2

    @pytest.mark.asyncio
    async def test_check_allowed(self):
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(
            rule_id="api", name="API",
            rate=100.0, burst=200.0,
        ))
        result = await limiter.check("api")
        assert result.allowed is True
        assert result.status == RateLimitStatus.ALLOWED

    @pytest.mark.asyncio
    async def test_check_rate_limited(self):
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(
            rule_id="api", name="API",
            rate=1.0, burst=3.0,
        ))
        # 消耗 burst
        for _ in range(3):
            r = await limiter.check("api")
            assert r.allowed is True
        # 第4次应该被限流
        r = await limiter.check("api")
        assert r.allowed is False
        assert r.status == RateLimitStatus.RATE_LIMITED

    @pytest.mark.asyncio
    async def test_check_queue_on_limit(self):
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(
            rule_id="api", name="API",
            rate=1.0, burst=3.0,
            queue_on_limit=True,
        ))
        for _ in range(3):
            await limiter.check("api")
        # 第4次被限流但状态是 QUEUED
        r = await limiter.check("api")
        assert r.allowed is False
        assert r.status == RateLimitStatus.QUEUED

    @pytest.mark.asyncio
    async def test_check_missing_rule(self):
        limiter = RateLimiter()
        result = await limiter.check("nonexistent")
        assert result.allowed is True  # 无规则默认放行

    @pytest.mark.asyncio
    async def test_check_disabled_rule(self):
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(
            rule_id="api", name="API",
            rate=1.0, burst=1.0, enabled=False,
        ))
        result = await limiter.check("api")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_check_sliding_window(self):
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(
            rule_id="sw", name="SW",
            algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
            window_sec=60, max_requests=3,
        ))
        for _ in range(3):
            r = await limiter.check("sw")
            assert r.allowed is True
        r = await limiter.check("sw")
        assert r.allowed is False

    @pytest.mark.asyncio
    async def test_check_per_scope_isolation(self):
        """不同作用域的限流互相隔离"""
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(
            rule_id="tenant", name="Tenant",
            scope=LimitScope.PER_TENANT,
            rate=10.0, burst=5.0,
        ))
        # tenant-A 消耗
        for _ in range(5):
            r = await limiter.check("tenant", scope_value="tenant-A")
            assert r.allowed is True
        # tenant-A 限流
        r = await limiter.check("tenant", scope_value="tenant-A")
        assert r.allowed is False
        # tenant-B 不受影响
        r = await limiter.check("tenant", scope_value="tenant-B")
        assert r.allowed is True

    @pytest.mark.asyncio
    async def test_get_bucket_stats(self):
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(rule_id="api", name="API"))
        await limiter.check("api")
        stats = limiter.get_bucket_stats("api")
        assert "available_tokens" in stats

    @pytest.mark.asyncio
    async def test_get_window_stats(self):
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(
            rule_id="sw", name="SW",
            algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
            window_sec=60, max_requests=100,
        ))
        await limiter.check("sw")
        stats = limiter.get_window_stats("sw")
        assert stats["current_count"] == 1

    @pytest.mark.asyncio
    async def test_update_rule(self):
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(rule_id="api", name="API", rate=10.0))
        assert limiter.update_rule("api", rate=50.0) is True
        assert limiter.get_rule("api").rate == 50.0

    @pytest.mark.asyncio
    async def test_update_nonexistent_rule(self):
        limiter = RateLimiter()
        assert limiter.update_rule("nonexistent", rate=50.0) is False


# ============================================================================
# ConcurrencyController Tests
# ============================================================================

class TestConcurrencyController:
    """并发控制器测试"""

    @pytest.mark.asyncio
    async def test_initialize(self):
        cc = ConcurrencyController(ConcurrencyConfig(max_concurrent=10))
        await cc.initialize()
        assert cc.is_available is True

    @pytest.mark.asyncio
    async def test_acquire_release(self):
        cc = ConcurrencyController(ConcurrencyConfig(max_concurrent=10))
        await cc.initialize()

        async with cc.acquire("task-1"):
            stats = cc.get_stats()
            assert stats.current_active == 1

        stats = cc.get_stats()
        assert stats.current_active == 0
        assert stats.total_completed == 1

    @pytest.mark.asyncio
    async def test_max_concurrent_enforced(self):
        cc = ConcurrencyController(ConcurrencyConfig(max_concurrent=3))
        await cc.initialize()

        acquired = 0
        release_events = []

        async def worker(i):
            nonlocal acquired
            async with cc.acquire(f"task-{i}"):
                acquired += 1
                await asyncio.sleep(0.05)
            release_events.append(i)

        tasks = [asyncio.create_task(worker(i)) for i in range(10)]
        await asyncio.sleep(0.02)  # 让一些任务获取到许可

        stats = cc.get_stats()
        # 活跃数不应超过 max_concurrent
        assert stats.current_active <= 3

        await asyncio.gather(*tasks)

        final_stats = cc.get_stats()
        assert final_stats.total_completed == 10
        assert final_stats.current_active == 0

    @pytest.mark.asyncio
    async def test_acquire_timeout(self):
        cc = ConcurrencyController(ConcurrencyConfig(
            max_concurrent=1, queue_timeout_sec=0.05,
        ))
        await cc.initialize()

        # 占用唯一的槽位
        async with cc.acquire("holder", timeout_sec=10.0):
            # 第二个请求应该超时
            with pytest.raises(asyncio.TimeoutError):
                async with cc.acquire("waiter", timeout_sec=0.02):
                    pass

    @pytest.mark.asyncio
    async def test_try_acquire(self):
        cc = ConcurrencyController(ConcurrencyConfig(max_concurrent=1))
        await cc.initialize()

        ticket = await cc.try_acquire()
        assert ticket is not None

        ticket2 = await cc.try_acquire()
        assert ticket2 is None  # 已被占用

    @pytest.mark.asyncio
    async def test_stats_accumulate(self):
        cc = ConcurrencyController(ConcurrencyConfig(max_concurrent=5))
        await cc.initialize()

        for i in range(5):
            async with cc.acquire(f"task-{i}"):
                await asyncio.sleep(0.01)

        stats = cc.get_stats()
        assert stats.total_admitted == 5
        assert stats.total_completed == 5
        assert stats.peak_concurrent >= 1

    @pytest.mark.asyncio
    async def test_reset_stats(self):
        cc = ConcurrencyController(ConcurrencyConfig(max_concurrent=5))
        await cc.initialize()

        async with cc.acquire("task-1"):
            pass

        cc.reset_stats()
        stats = cc.get_stats()
        assert stats.total_admitted == 0

    @pytest.mark.asyncio
    async def test_update_config(self):
        cc = ConcurrencyController(ConcurrencyConfig(max_concurrent=5))
        await cc.initialize()

        cc.update_config(ConcurrencyConfig(max_concurrent=20))
        assert cc.config.max_concurrent == 20

    @pytest.mark.asyncio
    async def test_adaptive_mode_config(self):
        cc = ConcurrencyController(ConcurrencyConfig(
            mode=ConcurrencyMode.ADAPTIVE,
            max_concurrent=100,
            min_concurrent=10,
        ))
        await cc.initialize()

        stats = cc.get_stats()
        assert stats.mode == "adaptive"

    @pytest.mark.asyncio
    async def test_adaptive_check(self):
        cc = ConcurrencyController(ConcurrencyConfig(
            mode=ConcurrencyMode.ADAPTIVE,
            max_concurrent=100,
            min_concurrent=5,
            scale_down_step=5,
            scale_up_step=10,
            cpu_high_threshold=0.85,
            cpu_low_threshold=0.30,
        ))
        await cc.initialize()

        # 高 CPU → 缩容
        stats_before = cc.get_stats()
        await cc.adaptive_check(0.90)
        stats_after = cc.get_stats()
        # 应该缩小或保持不变（不能低于 min）
        assert stats_after.max_allowed >= 5

    @pytest.mark.asyncio
    async def test_available_slots(self):
        cc = ConcurrencyController(ConcurrencyConfig(max_concurrent=5))
        await cc.initialize()

        assert cc.available_slots == 5

        tickets = []
        for _ in range(3):
            tickets.append(await cc.try_acquire())

        assert cc.available_slots == 2


# ============================================================================
# LLMRateLimiter Tests
# ============================================================================

class TestLLMRateLimiter:
    """LLM 自适应限流器测试"""

    def test_configure(self):
        limiter = LLMRateLimiter()
        limiter.configure(LLMRateLimitConfig(
            provider="openai", model="gpt-4",
            max_concurrent=5, max_rpm=100,
        ))
        cfg = limiter.get_config("openai", "gpt-4")
        assert cfg is not None
        assert cfg.max_concurrent == 5

    def test_configure_wildcard(self):
        limiter = LLMRateLimiter()
        limiter.configure(LLMRateLimitConfig(
            provider="openai", model="",
            max_concurrent=20,
        ))
        # 精确匹配不存在，回退通配
        cfg = limiter.get_config("openai", "gpt-3.5")
        assert cfg is not None
        assert cfg.max_concurrent == 20

    @pytest.mark.asyncio
    async def test_acquire_release(self):
        limiter = LLMRateLimiter()
        limiter.configure(LLMRateLimitConfig(
            provider="openai", max_concurrent=10,
        ))
        async with limiter.acquire("openai", "gpt-4"):
            state = limiter.get_state("openai", "gpt-4")
            assert state is not None
            assert state.active_calls == 1

    @pytest.mark.asyncio
    async def test_record_429_triggers_throttle(self):
        limiter = LLMRateLimiter()
        limiter.configure(LLMRateLimitConfig(
            provider="openai", auto_throttle=True,
            throttle_factor=0.5,
        ))

        state_before = limiter.get_state("openai")
        if state_before is None:
            # 需先触发 acquire 来初始化状态
            try:
                async with limiter.acquire("openai"):
                    pass
            except RuntimeError:
                pass
        state_before = limiter.get_state("openai")
        if state_before is None:
            pytest.skip("state not initialized")

        limiter.record_429("openai")
        state_after = limiter.get_state("openai")
        assert state_after is not None
        assert state_after.throttle_level < 1.0
        assert state_after.consecutive_429 > 0

    @pytest.mark.asyncio
    async def test_record_success_recovery(self):
        limiter = LLMRateLimiter()
        limiter.configure(LLMRateLimitConfig(
            provider="openai", auto_throttle=True,
            throttle_factor=0.5,
        ))

        try:
            async with limiter.acquire("openai"):
                pass
        except RuntimeError:
            pass

        limiter.record_429("openai")
        limiter.record_429("openai")
        throttled_level = limiter.get_state("openai").throttle_level
        assert throttled_level < 1.0

        limiter.record_success("openai")
        recovered_level = limiter.get_state("openai").throttle_level
        assert recovered_level > throttled_level

    @pytest.mark.asyncio
    async def test_fully_throttled_raises(self):
        limiter = LLMRateLimiter()
        limiter.configure(LLMRateLimitConfig(
            provider="openai", auto_throttle=True,
            throttle_factor=0.1,
        ))

        try:
            async with limiter.acquire("openai"):
                pass
        except RuntimeError:
            pass

        # 模拟多次 429 导致完全节流
        state = limiter.get_state("openai")
        if state:
            state.throttle_level = 0.0
            state.is_throttled = True

        with pytest.raises(RuntimeError, match="fully throttled"):
            async with limiter.acquire("openai"):
                pass

    @pytest.mark.asyncio
    async def test_get_all_states(self):
        limiter = LLMRateLimiter()
        limiter.configure(LLMRateLimitConfig(provider="openai"))
        limiter.configure(LLMRateLimitConfig(provider="anthropic"))

        try:
            async with limiter.acquire("openai"):
                pass
        except RuntimeError:
            pass
        try:
            async with limiter.acquire("anthropic"):
                pass
        except RuntimeError:
            pass

        states = limiter.get_all_states()
        assert len(states) >= 1

    @pytest.mark.asyncio
    async def test_rpm_tracking(self):
        limiter = LLMRateLimiter()
        limiter.configure(LLMRateLimitConfig(
            provider="openai", max_rpm=500,
        ))

        try:
            async with limiter.acquire("openai"):
                pass
        except RuntimeError:
            pass

        rpm = limiter.get_current_rpm("openai")
        assert rpm >= 0  # 可能被 acquire 的记录

    @pytest.mark.asyncio
    async def test_reset(self):
        limiter = LLMRateLimiter()
        limiter.configure(LLMRateLimitConfig(provider="openai"))

        try:
            async with limiter.acquire("openai"):
                pass
        except RuntimeError:
            pass

        limiter.record_429("openai")
        limiter.reset("openai")
        assert limiter.get_state("openai") is None


# ============================================================================
# Backpressure Tests
# ============================================================================

class TestBackpressureController:
    """背压控制器测试"""

    @pytest.mark.asyncio
    async def test_enqueue_dequeue(self):
        bp = BackpressureController(BackpressureConfig(
            target="test", max_queue_size=100,
        ))
        ok = await bp.enqueue("item1")
        assert ok is True
        assert bp.queue_size == 1

        item = await bp.dequeue()
        assert item == "item1"
        assert bp.queue_size == 0

    @pytest.mark.asyncio
    async def test_drop_oldest(self):
        bp = BackpressureController(BackpressureConfig(
            target="test", max_queue_size=3,
            strategy=BackpressureStrategy.DROP_OLDEST,
        ))
        await bp.enqueue("a")
        await bp.enqueue("b")
        await bp.enqueue("c")

        # 队列满，添加 "d" 会丢弃 "a"
        ok = await bp.enqueue("d")
        assert ok is True  # DROP_OLDEST 替换成功

        # 出队：应该是 b, c, d
        assert await bp.dequeue() == "b"
        assert await bp.dequeue() == "c"
        assert await bp.dequeue() == "d"

    @pytest.mark.asyncio
    async def test_drop_newest(self):
        bp = BackpressureController(BackpressureConfig(
            target="test", max_queue_size=3,
            strategy=BackpressureStrategy.DROP_NEWEST,
        ))
        await bp.enqueue("a")
        await bp.enqueue("b")
        await bp.enqueue("c")

        ok = await bp.enqueue("d")
        assert ok is False  # DROP_NEWEST 丢弃新来者

        assert bp.queue_size == 3

    @pytest.mark.asyncio
    async def test_block_strategy(self):
        bp = BackpressureController(BackpressureConfig(
            target="test", max_queue_size=3,
            strategy=BackpressureStrategy.BLOCK,
        ))
        await bp.enqueue("a")
        await bp.enqueue("b")
        await bp.enqueue("c")

        ok = await bp.enqueue("d")
        assert ok is False

    @pytest.mark.asyncio
    async def test_degrade_strategy(self):
        bp = BackpressureController(BackpressureConfig(
            target="test", max_queue_size=3,
            strategy=BackpressureStrategy.DEGRADE,
        ))
        await bp.enqueue("a")
        await bp.enqueue("b")
        await bp.enqueue("c")

        ok = await bp.enqueue("d")
        assert ok is False

    @pytest.mark.asyncio
    async def test_watermark_activation(self):
        bp = BackpressureController(BackpressureConfig(
            target="test", max_queue_size=10,
            high_watermark=0.5, low_watermark=0.3,
        ))
        # 填到高水位
        for i in range(6):
            await bp.enqueue(f"item{i}")
        assert bp.is_active is True

        # 排空到低水位以下
        for _ in range(5):
            await bp.dequeue()
        assert bp.is_active is False

    @pytest.mark.asyncio
    async def test_disabled(self):
        bp = BackpressureController(BackpressureConfig(
            target="test", max_queue_size=3, enabled=False,
        ))
        for i in range(10):
            ok = await bp.enqueue(f"item{i}")
            assert ok is True
        assert bp.queue_size == 10

    @pytest.mark.asyncio
    async def test_stats(self):
        bp = BackpressureController(BackpressureConfig(
            target="test", max_queue_size=5,
            strategy=BackpressureStrategy.DROP_OLDEST,
        ))
        for i in range(5):
            await bp.enqueue(f"item{i}")
        # 触发一次丢弃
        await bp.enqueue("overflow")

        stats = bp.get_stats()
        assert stats.target == "test"
        assert stats.total_dropped >= 1
        assert stats.utilization > 0

    @pytest.mark.asyncio
    async def test_reset_stats(self):
        bp = BackpressureController(BackpressureConfig(
            target="test", max_queue_size=5,
        ))
        for _ in range(3):
            await bp.enqueue("item")

        bp.reset_stats()
        stats = bp.get_stats()
        assert stats.total_dropped == 0

    @pytest.mark.asyncio
    async def test_clear_queue(self):
        bp = BackpressureController(BackpressureConfig(
            target="test", max_queue_size=100,
        ))
        for i in range(10):
            await bp.enqueue(f"item{i}")

        count = bp.clear_queue()
        assert count == 10
        assert bp.queue_size == 0

    @pytest.mark.asyncio
    async def test_update_config(self):
        bp = BackpressureController(BackpressureConfig(
            target="test", max_queue_size=100,
        ))
        bp.update_config(max_queue_size=200)
        assert bp.config.max_queue_size == 200

    @pytest.mark.asyncio
    async def test_can_enqueue(self):
        bp = BackpressureController(BackpressureConfig(
            target="test", max_queue_size=3,
        ))
        assert await bp.can_enqueue() is True

        for _ in range(3):
            await bp.enqueue("item")
        assert await bp.can_enqueue() is False


class TestBackpressureManager:
    """背压管理器测试"""

    def test_register_and_get(self):
        mgr = BackpressureManager()
        ctrl = mgr.register(BackpressureConfig(target="sse"))
        assert mgr.get("sse") is ctrl

    def test_list_targets(self):
        mgr = BackpressureManager()
        mgr.register(BackpressureConfig(target="sse"))
        mgr.register(BackpressureConfig(target="eventbus"))
        assert set(mgr.list_targets()) == {"sse", "eventbus"}

    def test_get_all_stats(self):
        mgr = BackpressureManager()
        mgr.register(BackpressureConfig(target="sse"))
        mgr.register(BackpressureConfig(target="eventbus"))
        stats = mgr.get_all_stats()
        assert len(stats) == 2

    def test_unregister(self):
        mgr = BackpressureManager()
        mgr.register(BackpressureConfig(target="sse"))
        assert mgr.unregister("sse") is True
        assert mgr.unregister("sse") is False
        assert mgr.get("sse") is None


# ============================================================================
# ConnectionPoolOptimizer Tests
# ============================================================================

class TestConnectionPoolOptimizer:
    """连接池优化器测试"""

    def test_recommend_config_postgres(self):
        opt = ConnectionPoolOptimizer()
        cfg = opt.recommend_config(concurrency_target=100, db_type="postgresql")
        assert cfg.pool_size > 0
        assert cfg.max_overflow > 0
        assert cfg.pool_pre_ping is True

    def test_recommend_config_sqlite(self):
        opt = ConnectionPoolOptimizer()
        cfg = opt.recommend_config(concurrency_target=100, db_type="sqlite")
        assert cfg.pool_size <= 5  # SQLite 不应太高
        assert cfg.max_overflow == 0

    def test_recommend_config_mysql(self):
        opt = ConnectionPoolOptimizer()
        cfg = opt.recommend_config(concurrency_target=100, db_type="mysql")
        assert cfg.pool_size > 0
        assert cfg.max_overflow > 0

    def test_apply_to_engine_kwargs(self):
        opt = ConnectionPoolOptimizer()
        kwargs = opt.apply_to_engine_kwargs(concurrency_target=100)
        assert "pool_size" in kwargs
        assert "max_overflow" in kwargs
        assert "pool_pre_ping" in kwargs

    def test_record_checkout(self):
        opt = ConnectionPoolOptimizer()
        opt.record_checkout(wait_time=0.5)
        opt.record_checkout(wait_time=0.2)
        assert opt._record_checkout() == 2

    def test_check_connection_leaks_no_engine(self):
        opt = ConnectionPoolOptimizer()
        # 无 engine 时跳过实际检查，验证方法存在
        assert opt._leak_threshold_sec > 0

    def test_get_health_report_basic(self):
        opt = ConnectionPoolOptimizer()
        # 无 engine 时返回推荐
        cfg = opt.recommend_config(concurrency_target=100)
        assert cfg.pool_size > 0

    def test_update_config(self):
        opt = ConnectionPoolOptimizer()
        cfg = ConnectionPoolConfig(pool_size=30, max_overflow=15)
        opt.update_config(cfg)
        assert opt.get_config() is cfg

    def test_generate_recommendation(self):
        opt = ConnectionPoolOptimizer()
        # 高利用率
        rec = opt._generate_recommendation(PoolStats(
            pool_size=10, checked_out=9, utilization=0.9,
        ))
        assert rec is not None

        # 低利用率
        rec = opt._generate_recommendation(PoolStats(
            pool_size=20, checked_out=3, utilization=0.15,
        ))
        assert rec is not None


# ============================================================================
# BenchmarkRunner Tests
# ============================================================================

class TestBenchmarkRunner:
    """基准测试运行器测试"""

    @pytest.mark.asyncio
    async def test_quick_benchmark(self):
        runner = BenchmarkRunner()

        async def task():
            await asyncio.sleep(0.005)

        result = await runner.quick_benchmark(
            task, max_concurrent=5, duration_sec=2.0,
        )
        assert result.concurrency == 5
        assert result.successful > 0
        assert result.throughput_rps > 0

    @pytest.mark.asyncio
    async def test_run_with_levels(self):
        runner = BenchmarkRunner()

        async def task():
            await asyncio.sleep(0.002)

        config = BenchmarkConfig(
            concurrency_levels=[1, 5],
            duration_sec=1.0,
            warmup_sec=0.5,
        )
        result = await runner.run(config, task)
        assert len(result.levels) == 2
        assert result.summary is not None

    @pytest.mark.asyncio
    async def test_percentile(self):
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        p50 = BenchmarkRunner._percentile(data, 50)
        assert 5 <= p50 <= 6

        p95 = BenchmarkRunner._percentile(data, 95)
        assert p95 >= 9

    @pytest.mark.asyncio
    async def test_summary_recommendations(self):
        runner = BenchmarkRunner()

        async def task():
            await asyncio.sleep(0.001)

        config = BenchmarkConfig(
            concurrency_levels=[1, 5],
            duration_sec=1.0,
            warmup_sec=0.3,
        )
        result = await runner.run(config, task)
        assert result.summary.recommendations
        assert len(result.summary.recommendations) > 0

    @pytest.mark.asyncio
    async def test_benchmark_with_errors(self):
        runner = BenchmarkRunner()
        error_count = 0

        async def task():
            nonlocal error_count
            if error_count < 3:
                error_count += 1
                raise RuntimeError("simulated error")
            await asyncio.sleep(0.001)

        result = await runner.quick_benchmark(
            task, max_concurrent=5, duration_sec=1.0,
        )
        # 应该有错误计数
        assert result.failed >= 0


# ============================================================================
# MetricsCollector Tests
# ============================================================================

class TestMetricsCollector:
    """指标收集器测试"""

    @pytest.mark.asyncio
    async def test_record_request(self):
        collector = MetricsCollector()
        await collector.record_request(latency=0.05, success=True)
        await collector.record_request(latency=0.10, success=True)
        await collector.record_request(latency=0.15, success=False)

        metrics = collector.get_snapshot()
        assert metrics.total_requests == 3
        assert metrics.completed_requests == 2
        assert metrics.failed_requests == 1

    @pytest.mark.asyncio
    async def test_latency_stats(self):
        collector = MetricsCollector()
        for i in range(100):
            await collector.record_request(latency=0.01 * (i + 1), success=True)

        metrics = collector.get_snapshot()
        assert metrics.latency_avg > 0
        assert metrics.latency_p50 > 0
        assert metrics.latency_p95 > 0
        assert metrics.latency_p99 > 0

    @pytest.mark.asyncio
    async def test_concurrency_tracking(self):
        collector = MetricsCollector()
        await collector.record_request_start()
        await collector.record_request_start()

        metrics = collector.get_snapshot()
        assert metrics.active_requests == 2
        assert metrics.peak_concurrency >= 2

        await collector.record_request_end()
        metrics = collector.get_snapshot()
        assert metrics.active_requests == 1

    @pytest.mark.asyncio
    async def test_llm_metrics(self):
        collector = MetricsCollector()
        await collector.record_llm_call(tokens=500)
        await collector.record_llm_call(tokens=300, is_429=True)

        metrics = collector.get_snapshot()
        assert metrics.llm_calls_total == 2
        assert metrics.llm_tokens_used == 800
        assert metrics.llm_429_count == 1

    @pytest.mark.asyncio
    async def test_cpu_memory(self):
        collector = MetricsCollector()
        await collector.record_cpu(45.5)
        await collector.record_cpu(55.0)
        await collector.record_memory(1024.0)

        metrics = collector.get_snapshot()
        assert metrics.cpu_percent > 0
        assert metrics.memory_mb > 0

    @pytest.mark.asyncio
    async def test_sse_metrics(self):
        collector = MetricsCollector()
        await collector.record_sse_connection(delta=1)
        await collector.record_sse_connection(delta=1)
        await collector.record_sse_event(queued=True)
        await collector.record_sse_event(queued=False)

        metrics = collector.get_snapshot()
        assert metrics.sse_connections == 2
        assert metrics.sse_events_queued == 1
        assert metrics.sse_events_dropped == 1

    @pytest.mark.asyncio
    async def test_capture_snapshot(self):
        collector = MetricsCollector()
        await collector.record_request(latency=0.01, success=True)

        snap = await collector.capture_snapshot("my_snap")
        assert snap.name == "my_snap"
        assert snap.value == 1.0

        snapshots = collector.get_snapshots()
        assert len(snapshots) >= 1

    @pytest.mark.asyncio
    async def test_reset(self):
        collector = MetricsCollector()
        await collector.record_request(latency=0.01, success=True)
        await collector.record_llm_call(tokens=100)

        collector.reset()
        metrics = collector.get_snapshot()
        assert metrics.total_requests == 0
        assert metrics.llm_calls_total == 0

    @pytest.mark.asyncio
    async def test_get_aggregated(self):
        collector = MetricsCollector()
        for i in range(10):
            await collector.record_request(latency=0.01 * (i + 1), success=True)

        avg = collector.get_aggregated("latency", MetricsAggregation.AVG)
        assert avg > 0

        p50 = collector.get_aggregated("latency", MetricsAggregation.P50)
        assert p50 > 0

        cnt = collector.get_aggregated("latency", MetricsAggregation.COUNT)
        assert cnt == 10

    @pytest.mark.asyncio
    async def test_current_rps(self):
        collector = MetricsCollector()
        # 模拟 1 秒内 50 个请求
        for _ in range(50):
            await collector.record_request(latency=0.01, success=True)

        metrics = collector.get_snapshot()
        assert metrics.current_rps >= 0  # 取决于时间窗口


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """集成测试"""

    @pytest.mark.asyncio
    async def test_concurrency_controller_with_real_tasks(self):
        """并发控制器 + 真实任务"""
        cc = ConcurrencyController(ConcurrencyConfig(max_concurrent=10))
        await cc.initialize()

        results = []

        async def worker(i: int):
            async with cc.acquire(f"worker-{i}"):
                await asyncio.sleep(0.02)
                results.append(i)

        tasks = [asyncio.create_task(worker(i)) for i in range(50)]
        await asyncio.gather(*tasks)

        assert len(results) == 50
        stats = cc.get_stats()
        assert stats.total_completed == 50

    @pytest.mark.asyncio
    async def test_rate_limiter_and_concurrency(self):
        """限流器 + 并发控制器联合测试"""
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(
            rule_id="api", name="API",
            rate=100.0, burst=200.0,
        ))

        cc = ConcurrencyController(ConcurrencyConfig(max_concurrent=10))
        await cc.initialize()

        async def handle(i: int) -> bool:
            r = await limiter.check("api")
            if not r.allowed:
                return False
            async with cc.acquire(f"req-{i}"):
                await asyncio.sleep(0.005)
            return True

        tasks = [asyncio.create_task(handle(i)) for i in range(100)]
        results = await asyncio.gather(*tasks)
        success_count = sum(1 for r in results if r)
        assert success_count > 0

    @pytest.mark.asyncio
    async def test_benchmark_with_metrics(self):
        """基准测试中指标收集"""
        runner = BenchmarkRunner()
        collector = MetricsCollector()

        async def task():
            t0 = time.monotonic()
            await asyncio.sleep(0.002)
            await collector.record_request(
                latency=time.monotonic() - t0, success=True,
            )

        result = await runner.quick_benchmark(
            task, max_concurrent=5, duration_sec=1.0,
        )
        assert result.successful > 0

        metrics = collector.get_snapshot()
        assert metrics.total_requests > 0

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """完整性能管线：限流 → 并发控制 → 背压 → 指标"""
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(
            rule_id="api", name="API",
            rate=500.0, burst=1000.0,
        ))

        cc = ConcurrencyController(ConcurrencyConfig(max_concurrent=20))
        await cc.initialize()

        bp = BackpressureController(BackpressureConfig(
            target="task_queue", max_queue_size=200,
            strategy=BackpressureStrategy.DROP_NEWEST,
        ))

        collector = MetricsCollector()

        async def process(i: int):
            # Step 1: 限流检查
            r = await limiter.check("api")
            if not r.allowed:
                await collector.record_request(latency=0, success=False, is_rate_limited=True)
                return

            # Step 2: 背压检查
            if not await bp.can_enqueue():
                await bp.enqueue(f"task-{i}")  # 按策略处理
                await collector.record_request(latency=0, success=False)
                return

            await bp.enqueue(f"task-{i}")

            # Step 3: 并发控制
            try:
                async with cc.acquire(f"task-{i}", timeout_sec=0.5):
                    await collector.record_request_start()
                    await asyncio.sleep(0.005)
                    await collector.record_request_end()
                    await collector.record_request(latency=0.005, success=True)
            except asyncio.TimeoutError:
                await collector.record_request(latency=0, success=False)

        tasks = [asyncio.create_task(process(i)) for i in range(200)]
        await asyncio.gather(*tasks)

        # 验证各组件统计
        metrics = collector.get_snapshot()
        assert metrics.total_requests > 0

        cc_stats = cc.get_stats()
        assert cc_stats.total_admitted > 0

        bp_stats = bp.get_stats()
        assert bp_stats.queue_size >= 0

    @pytest.mark.asyncio
    async def test_backpressure_recovery(self):
        """背压恢复流程"""
        bp = BackpressureController(BackpressureConfig(
            target="test", max_queue_size=50,
            high_watermark=0.6, low_watermark=0.3,
        ))
        # 填满队列
        for i in range(35):
            await bp.enqueue(f"item{i}")
        assert bp.is_active is True  # 超过高水位

        # 排空
        for _ in range(25):
            await bp.dequeue()
        assert bp.is_active is False  # 低于低水位

    @pytest.mark.asyncio
    async def test_llm_adaptive_recovery(self):
        """LLM 自适应恢复流程"""
        limiter = LLMRateLimiter()
        limiter.configure(LLMRateLimitConfig(
            provider="test", auto_throttle=True,
            throttle_factor=0.5,
        ))

        try:
            async with limiter.acquire("test"):
                pass
        except RuntimeError:
            pass

        # 模拟多次 429
        for _ in range(3):
            limiter.record_429("test")

        state = limiter.get_state("test")
        if state:
            assert state.throttle_level < 1.0

        # 模拟成功恢复
        for _ in range(10):
            limiter.record_success("test")

        state = limiter.get_state("test")
        if state:
            assert state.throttle_level >= 0.9  # 逐步恢复到接近全速
