"""W35-36 Performance Optimization — 数据模型

性能优化模块的数据模型定义：
- BenchmarkConfig / BenchmarkResult：基准测试配置与结果
- PerformanceMetrics / MetricSnapshot：性能指标快照
- RateLimitRule / RateLimitResult：限流规则与结果
- ConcurrencyConfig / ConcurrencyStats：并发控制配置与统计
- BackpressureConfig / BackpressurePolicy：背压配置与策略
- ConnectionPoolConfig / PoolStats：连接池配置与统计
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime, timezone


# ============================================================================
# Enums
# ============================================================================

class ConcurrencyMode(str, Enum):
    """并发控制模式"""
    FIXED = "fixed"           # 固定上限
    ADAPTIVE = "adaptive"     # 自适应（根据系统负载动态调整）
    UNLIMITED = "unlimited"   # 不限制（仅开发/测试）


class RateLimitAlgorithm(str, Enum):
    """限流算法"""
    TOKEN_BUCKET = "token_bucket"       # 令牌桶
    SLIDING_WINDOW = "sliding_window"   # 滑动窗口
    LEAKY_BUCKET = "leaky_bucket"       # 漏桶
    FIXED_WINDOW = "fixed_window"       # 固定窗口


class LimitScope(str, Enum):
    """限流作用域"""
    GLOBAL = "global"         # 全局限流
    PER_TENANT = "per_tenant" # 按租户
    PER_USER = "per_user"     # 按用户
    PER_IP = "per_ip"         # 按 IP
    PER_ENDPOINT = "per_endpoint"  # 按端点


class RateLimitStatus(str, Enum):
    """限流状态"""
    ALLOWED = "allowed"           # 放行
    RATE_LIMITED = "rate_limited" # 被限流
    QUEUED = "queued"             # 排队等待


class BackpressureStrategy(str, Enum):
    """背压策略"""
    DROP_OLDEST = "drop_oldest"     # 丢弃最旧的
    DROP_NEWEST = "drop_newest"     # 丢弃最新的
    BLOCK = "block"                 # 阻塞等待（可能超时）
    DEGRADE = "degrade"             # 降级（返回简化结果）


class MetricsAggregation(str, Enum):
    """指标聚合方式"""
    AVG = "avg"
    P50 = "p50"
    P95 = "p95"
    P99 = "p99"
    MAX = "max"
    MIN = "min"
    SUM = "sum"
    COUNT = "count"


# ============================================================================
# Benchmark Models
# ============================================================================

@dataclass
class BenchmarkConfig:
    """基准测试配置"""
    concurrency_levels: list[int] = field(default_factory=lambda: [1, 10, 50, 100])
    """并发级别列表，如 [1, 10, 50, 100]"""
    duration_sec: float = 30.0
    """每级测试持续时间（秒）"""
    warmup_sec: float = 5.0
    """预热时间（秒）"""
    task_payload_template: dict = field(default_factory=dict)
    """任务负载模板"""
    max_retries_per_level: int = 3
    """每级最大重试次数"""


@dataclass
class BenchmarkResult:
    """基准测试结果"""
    benchmark_id: str = ""
    config: Optional[BenchmarkConfig] = None
    levels: list["ConcurrencyLevelResult"] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    summary: Optional["BenchmarkSummary"] = None


@dataclass
class ConcurrencyLevelResult:
    """单个并发级别的测试结果"""
    concurrency: int = 0
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    rate_limited: int = 0
    # 延迟统计（秒）
    latency_avg: float = 0.0
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
    latency_max: float = 0.0
    latency_min: float = 0.0
    # 吞吐
    throughput_rps: float = 0.0
    # 错误
    error_rate: float = 0.0
    # 资源
    avg_concurrent_tasks: float = 0.0
    peak_concurrent_tasks: int = 0


@dataclass
class BenchmarkSummary:
    """基准测试汇总"""
    max_sustainable_concurrency: int = 0
    """最大可持续并发数（错误率 < 1%）"""
    peak_throughput_rps: float = 0.0
    """峰值吞吐"""
    p99_latency_at_target: float = 0.0
    """目标并发下的 P99 延迟"""
    total_errors: int = 0
    overall_error_rate: float = 0.0
    recommendations: list[str] = field(default_factory=list)


# ============================================================================
# Performance Metrics Models
# ============================================================================

@dataclass
class PerformanceMetrics:
    """性能指标集合"""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # 请求指标
    total_requests: int = 0
    active_requests: int = 0
    completed_requests: int = 0
    failed_requests: int = 0
    rate_limited_requests: int = 0
    # 延迟（秒）
    latency_avg: float = 0.0
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
    # 吞吐
    current_rps: float = 0.0
    avg_rps: float = 0.0
    peak_rps: float = 0.0
    # 错误
    error_rate: float = 0.0
    # 并发
    current_concurrency: int = 0
    peak_concurrency: int = 0
    # LLM 调用
    llm_calls_total: int = 0
    llm_calls_active: int = 0
    llm_tokens_used: int = 0
    llm_429_count: int = 0
    # 系统资源
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    db_connections_active: int = 0
    db_connections_idle: int = 0
    # SSE
    sse_connections: int = 0
    sse_events_queued: int = 0
    sse_events_dropped: int = 0


@dataclass
class MetricSnapshot:
    """单点指标快照"""
    metric_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    name: str = ""
    value: float = 0.0
    labels: dict[str, str] = field(default_factory=dict)
    unit: str = ""


# ============================================================================
# Rate Limiter Models
# ============================================================================

@dataclass
class RateLimitRule:
    """限流规则"""
    rule_id: str = ""
    name: str = ""
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET
    scope: LimitScope = LimitScope.GLOBAL
    scope_value: str = ""  # tenant_id / user_id / ip / endpoint
    # Token Bucket 参数
    rate: float = 100.0        # 令牌生成速率（个/秒）
    burst: float = 200.0       # 突发容量（桶大小）
    # Sliding Window 参数
    window_sec: float = 60.0   # 窗口大小（秒）
    max_requests: int = 1000   # 窗口内最大请求数
    # 行为
    enabled: bool = True
    queue_on_limit: bool = False  # 超限时是否排队
    queue_timeout_sec: float = 5.0  # 排队超时
    retry_after_header: bool = True  # 是否返回 Retry-After 头


@dataclass
class RateLimitResult:
    """限流判定结果"""
    allowed: bool = True
    status: RateLimitStatus = RateLimitStatus.ALLOWED
    remaining: int = 0
    limit: int = 0
    reset_at: str = ""
    retry_after_sec: float = 0.0
    rule_id: str = ""
    reason: str = ""


# ============================================================================
# Concurrency Control Models
# ============================================================================

@dataclass
class ConcurrencyConfig:
    """并发控制配置"""
    mode: ConcurrencyMode = ConcurrencyMode.FIXED
    max_concurrent: int = 100
    """最大并发任务数"""
    min_concurrent: int = 10
    """最小并发数（自适应模式）"""
    # 自适应参数
    cpu_high_threshold: float = 0.85  # CPU 高于此值缩容
    cpu_low_threshold: float = 0.30   # CPU 低于此值扩容
    scale_up_step: int = 10           # 每次扩容步长
    scale_down_step: int = 5          # 每次缩容步长
    cooldown_sec: float = 30.0        # 扩缩容冷却时间
    # 等待队列
    queue_max_size: int = 500         # 等待队列最大长度
    queue_timeout_sec: float = 60.0   # 队列等待超时


@dataclass
class ConcurrencyStats:
    """并发控制统计"""
    max_allowed: int = 0
    current_active: int = 0
    queue_length: int = 0
    total_admitted: int = 0
    total_rejected: int = 0
    total_completed: int = 0
    total_timed_out: int = 0
    avg_wait_time_sec: float = 0.0
    peak_concurrent: int = 0
    mode: str = "fixed"


# ============================================================================
# Backpressure Models
# ============================================================================

@dataclass
class BackpressureConfig:
    """背压配置"""
    target: str = ""  # "sse" | "eventbus" | "task_queue"
    max_queue_size: int = 1000
    strategy: BackpressureStrategy = BackpressureStrategy.DROP_OLDEST
    high_watermark: float = 0.8   # 高水位线（队列占比），触发背压
    low_watermark: float = 0.5    # 低水位线，解除背压
    enabled: bool = True


@dataclass
class BackpressureStats:
    """背压统计"""
    target: str = ""
    queue_size: int = 0
    max_size: int = 0
    utilization: float = 0.0
    is_active: bool = False  # 背压是否激活
    total_dropped: int = 0
    total_degraded: int = 0
    total_blocked: int = 0
    strategy: str = ""


# ============================================================================
# Connection Pool Models
# ============================================================================

@dataclass
class ConnectionPoolConfig:
    """数据库连接池配置"""
    pool_size: int = 20
    """连接池基础大小"""
    max_overflow: int = 10
    """最大溢出连接数"""
    pool_timeout: float = 30.0
    """获取连接超时（秒）"""
    pool_recycle: float = 3600.0
    """连接回收时间（秒），-1 不回收"""
    pool_pre_ping: bool = True
    """获取连接前先 ping 验证"""
    echo_pool: bool = False
    """是否输出连接池日志"""


@dataclass
class PoolStats:
    """连接池统计"""
    pool_size: int = 0
    checked_in: int = 0       # 空闲连接数
    checked_out: int = 0      # 使用中连接数
    overflow: int = 0         # 溢出连接数
    total_connections: int = 0
    max_connections: int = 0
    utilization: float = 0.0
    total_checked_out: int = 0  # 历史总 checkout 次数
    total_wait_count: int = 0   # 历史等待连接次数


# ============================================================================
# LLM Rate Limiter Models
# ============================================================================

@dataclass
class LLMRateLimitConfig:
    """LLM 调用限流配置"""
    provider: str = ""  # openai / anthropic / ollama
    model: str = ""     # 空=所有模型
    max_concurrent: int = 10
    max_rpm: int = 500       # 每分钟最大请求数
    max_tpm: int = 1_000_000 # 每分钟最大 Token 数
    # 自适应参数
    auto_throttle: bool = True    # 收到 429 自动降速
    throttle_factor: float = 0.5  # 降速因子
    recovery_window_sec: float = 30.0  # 恢复窗口
    # 重试
    max_retries_on_429: int = 3
    retry_backoff_base: float = 1.0


@dataclass
class LLMRateLimitState:
    """LLM 限流运行时状态"""
    provider: str = ""
    model: str = ""
    current_rpm: int = 0
    current_tpm: int = 0
    active_calls: int = 0
    throttle_level: float = 1.0  # 1.0 = 全速, 0.0 = 完全限流
    consecutive_429: int = 0
    last_429_time: str = ""
    total_429_count: int = 0
    is_throttled: bool = False
