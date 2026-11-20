"""W35-36 Performance Optimization — 基准测试运行器

BenchmarkRunner 提供系统性能基准测试能力：
- 多级并发压测（1 → 10 → 50 → 100）
- 延迟分布统计（avg/p50/p95/p99/max/min）
- 吞吐量计算（RPS）
- 错误率统计
- 预热支持
- 结果汇总与建议

使用方式：
    runner = BenchmarkRunner()
    result = await runner.run(
        config=BenchmarkConfig(concurrency_levels=[1, 10, 50, 100]),
        task_factory=lambda: asyncio.sleep(0.01)
    )
"""

import asyncio
import time
import statistics
import uuid
from typing import Optional, Callable, Awaitable

from .models import (
    BenchmarkConfig, BenchmarkResult, ConcurrencyLevelResult,
    BenchmarkSummary
)
from .concurrency_controller import ConcurrencyController
from .models import ConcurrencyConfig, ConcurrencyMode


class BenchmarkRunner:
    """性能基准测试执行器

    按配置的并发级别逐步压测，收集每级指标。
    """

    def __init__(self):
        self._concurrency_controller: Optional[ConcurrencyController] = None

    # ------------------------------------------------------------------
    # 主 API
    # ------------------------------------------------------------------

    async def run(self, config: BenchmarkConfig,
                  task_factory: Callable[[], Awaitable],
                  setup: Optional[Callable[[], Awaitable]] = None,
                  teardown: Optional[Callable[[], Awaitable]] = None,
                  ) -> BenchmarkResult:
        """执行基准测试

        Args:
            config: 测试配置
            task_factory: 任务工厂函数（每次调用返回一个协程）
            setup: 每级测试前的 setup
            teardown: 每级测试后的 teardown

        Returns:
            BenchmarkResult: 完整测试结果
        """
        benchmark_id = str(uuid.uuid4())[:8]
        result = BenchmarkResult(
            benchmark_id=benchmark_id,
            config=config,
            started_at=str(time.time()),
        )

        # 预热
        if config.warmup_sec > 0:
            await self._warmup(config.warmup_sec, task_factory)

        for level in config.concurrency_levels:
            level_result = await self._run_level(
                level=level,
                config=config,
                task_factory=task_factory,
                setup=setup,
                teardown=teardown,
            )
            result.levels.append(level_result)

        result.completed_at = str(time.time())
        result.summary = self._generate_summary(result)
        return result

    # ------------------------------------------------------------------
    # 单级测试
    # ------------------------------------------------------------------

    async def _run_level(self, level: int, config: BenchmarkConfig,
                         task_factory: Callable[[], Awaitable],
                         setup: Optional[Callable[[], Awaitable]],
                         teardown: Optional[Callable[[], Awaitable]],
                         ) -> ConcurrencyLevelResult:
        """执行单个并发级别的测试"""
        cc = ConcurrencyController(ConcurrencyConfig(
            mode=ConcurrencyMode.FIXED,
            max_concurrent=level,
            queue_max_size=level * 2,
        ))
        await cc.initialize()

        latencies: list[float] = []
        errors = 0
        rate_limited = 0
        active_samples: list[int] = []

        if setup:
            await setup()

        start_time = time.monotonic()
        end_time = start_time + config.duration_sec

        tasks: list[asyncio.Task] = []

        async def worker(worker_id: int):
            nonlocal errors, rate_limited
            while time.monotonic() < end_time:
                try:
                    async with cc.acquire(f"bench-{worker_id}", timeout_sec=5.0):
                        t0 = time.monotonic()
                        await task_factory()
                        elapsed = time.monotonic() - t0
                        latencies.append(elapsed)
                except asyncio.TimeoutError:
                    rate_limited += 1
                except Exception:
                    errors += 1

                # 采样活跃并发数
                active_samples.append(cc.get_stats().current_active)

        # 启动 level 个 worker
        for i in range(level):
            tasks.append(asyncio.create_task(worker(i)))

        # 等待测试时长
        await asyncio.sleep(config.duration_sec)

        # 取消所有 worker
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        actual_duration = time.monotonic() - start_time

        if teardown:
            await teardown()

        # 计算统计
        total = len(latencies) + errors + rate_limited
        successful = len(latencies)

        return ConcurrencyLevelResult(
            concurrency=level,
            total_requests=total,
            successful=successful,
            failed=errors,
            rate_limited=rate_limited,
            latency_avg=round(statistics.mean(latencies), 6) if latencies else 0,
            latency_p50=round(self._percentile(latencies, 50), 6) if latencies else 0,
            latency_p95=round(self._percentile(latencies, 95), 6) if latencies else 0,
            latency_p99=round(self._percentile(latencies, 99), 6) if latencies else 0,
            latency_max=round(max(latencies), 6) if latencies else 0,
            latency_min=round(min(latencies), 6) if latencies else 0,
            throughput_rps=round(total / actual_duration, 2) if actual_duration > 0 else 0,
            error_rate=round(errors / total, 4) if total > 0 else 0,
            avg_concurrent_tasks=round(
                sum(active_samples) / len(active_samples), 1
            ) if active_samples else 0,
            peak_concurrent_tasks=max(active_samples) if active_samples else 0,
        )

    # ------------------------------------------------------------------
    # 快速基准测试
    # ------------------------------------------------------------------

    async def quick_benchmark(self, task_factory: Callable[[], Awaitable],
                               max_concurrent: int = 100,
                               duration_sec: float = 10.0,
                               ) -> ConcurrencyLevelResult:
        """快速单级基准测试

        在指定并发级别下运行简短的测试。
        """
        config = BenchmarkConfig(
            concurrency_levels=[max_concurrent],
            duration_sec=duration_sec,
            warmup_sec=2.0,
        )
        result = await self.run(config, task_factory)
        return result.levels[0] if result.levels else ConcurrencyLevelResult()

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    async def _warmup(self, duration_sec: float,
                      task_factory: Callable[[], Awaitable]) -> None:
        """预热"""
        end_time = time.monotonic() + duration_sec
        tasks = []
        async def _warm():
            while time.monotonic() < end_time:
                await task_factory()

        for _ in range(5):
            tasks.append(asyncio.create_task(_warm()))

        await asyncio.sleep(duration_sec)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _percentile(data: list[float], p: float) -> float:
        """计算百分位数"""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * p / 100.0
        f = int(k)
        c = k - f
        if f + 1 < len(sorted_data):
            return sorted_data[f] + c * (sorted_data[f + 1] - sorted_data[f])
        return sorted_data[f]

    def _generate_summary(self, result: BenchmarkResult) -> BenchmarkSummary:
        """生成测试汇总与建议"""
        if not result.levels:
            return BenchmarkSummary()

        # 找最大可持续并发（错误率 < 1%）
        max_sustainable = 0
        peak_rps = 0.0
        p99_at_target = 0.0

        for lr in result.levels:
            if lr.error_rate < 0.01:
                max_sustainable = lr.concurrency
                p99_at_target = lr.latency_p99
            if lr.throughput_rps > peak_rps:
                peak_rps = lr.throughput_rps

        total_errors = sum(lr.failed for lr in result.levels)
        total_requests = sum(lr.total_requests for lr in result.levels)
        overall_error_rate = total_errors / total_requests if total_requests > 0 else 0

        recommendations = []
        target = result.config.concurrency_levels[-1] if result.config else 100

        if max_sustainable < target:
            recommendations.append(
                f"System can only sustain {max_sustainable} concurrent (target: {target}). "
                "Consider increasing connection pool size or optimizing slow paths."
            )
        else:
            recommendations.append(
                f"System sustains target concurrency of {target}. "
                f"P99 latency at target: {p99_at_target*1000:.1f}ms."
            )

        if overall_error_rate > 0.05:
            recommendations.append(
                f"High error rate ({overall_error_rate:.1%}). "
                "Investigate timeout/connection errors under load."
            )

        if result.levels:
            last_level = result.levels[-1]
            if last_level.rate_limited > last_level.total_requests * 0.1:
                recommendations.append(
                    "High rate-limit rejection rate. Consider increasing rate limits or optimizing throughput."
                )

        return BenchmarkSummary(
            max_sustainable_concurrency=max_sustainable,
            peak_throughput_rps=peak_rps,
            p99_latency_at_target=p99_at_target,
            total_errors=total_errors,
            overall_error_rate=round(overall_error_rate, 4),
            recommendations=recommendations,
        )
