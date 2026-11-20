"""W35-36 Performance Optimization — 性能优化模块

性能优化模块提供 100 并发目标下的系统优化能力：

核心组件：
- BenchmarkRunner：基准测试运行器（多级并发压测）
- MetricsCollector：性能指标收集器（实时 + 历史）
- ConcurrencyController：全局并发控制器（asyncio.Semaphore + 自适应）
- RateLimiter：API 限流器（Token Bucket / Sliding Window）
- LLMRateLimiter：LLM 自适应限流器（429 检测 + 自动降速）
- BackpressureController / BackpressureManager：背压保护
- ConnectionPoolOptimizer：连接池优化器

公共 API：
  Core: BenchmarkRunner, MetricsCollector, ConcurrencyController,
         RateLimiter, LLMRateLimiter, BackpressureController,
         BackpressureManager, ConnectionPoolOptimizer
  Config: BenchmarkConfig, ConcurrencyConfig, RateLimitRule,
          LLMRateLimitConfig, BackpressureConfig, ConnectionPoolConfig
  Results: BenchmarkResult, ConcurrencyLevelResult, PerformanceMetrics,
           RateLimitResult, ConcurrencyStats, BackpressureStats, PoolStats
  Enums: ConcurrencyMode, RateLimitAlgorithm, LimitScope, RateLimitStatus,
         BackpressureStrategy, MetricsAggregation
"""

from app.runtime.performance.concurrency_controller import ConcurrencyController
from app.runtime.performance.rate_limiter import RateLimiter, TokenBucket, SlidingWindow, PRESET_RULES
from app.runtime.performance.llm_rate_limiter import LLMRateLimiter
from app.runtime.performance.backpressure import BackpressureController, BackpressureManager
from app.runtime.performance.connection_pool import ConnectionPoolOptimizer
from app.runtime.performance.benchmark_runner import BenchmarkRunner
from app.runtime.performance.metrics_collector import MetricsCollector
from app.runtime.performance.models import (
    # Config
    BenchmarkConfig, ConcurrencyConfig, RateLimitRule, LLMRateLimitConfig,
    BackpressureConfig, ConnectionPoolConfig,
    # Results
    BenchmarkResult, ConcurrencyLevelResult, BenchmarkSummary,
    PerformanceMetrics, MetricSnapshot,
    RateLimitResult, ConcurrencyStats, BackpressureStats, PoolStats,
    LLMRateLimitState,
    # Enums
    ConcurrencyMode, RateLimitAlgorithm, LimitScope, RateLimitStatus,
    BackpressureStrategy, MetricsAggregation,
)

__all__ = [
    # Core
    "BenchmarkRunner",
    "MetricsCollector",
    "ConcurrencyController",
    "RateLimiter",
    "TokenBucket",
    "SlidingWindow",
    "LLMRateLimiter",
    "BackpressureController",
    "BackpressureManager",
    "ConnectionPoolOptimizer",
    # Config
    "BenchmarkConfig",
    "ConcurrencyConfig",
    "RateLimitRule",
    "LLMRateLimitConfig",
    "BackpressureConfig",
    "ConnectionPoolConfig",
    # Results
    "BenchmarkResult",
    "ConcurrencyLevelResult",
    "BenchmarkSummary",
    "PerformanceMetrics",
    "MetricSnapshot",
    "RateLimitResult",
    "ConcurrencyStats",
    "BackpressureStats",
    "PoolStats",
    "LLMRateLimitState",
    # Presets
    "PRESET_RULES",
    # Enums
    "ConcurrencyMode",
    "RateLimitAlgorithm",
    "LimitScope",
    "RateLimitStatus",
    "BackpressureStrategy",
    "MetricsAggregation",
]
