"""W35-36 Performance Optimization — 性能指标收集器

MetricsCollector 提供系统级性能指标的实时收集与聚合：
- 请求指标：总数/活跃/完成/失败/限流
- 延迟分布：avg/p50/p95/p99
- 吞吐量：current RPS / avg RPS / peak RPS
- 并发数：当前/峰值
- LLM 调用指标：调用数/429 数/Token 使用量
- 系统资源：CPU/内存
- 快照存储与历史查询

使用方式：
    collector = MetricsCollector()
    collector.record_request(latency=0.05, success=True)
    metrics = collector.get_snapshot()
"""

import asyncio
import time
import statistics
import uuid
from typing import Optional
from collections import deque

from .models import (
    PerformanceMetrics, MetricSnapshot, MetricsAggregation
)


class MetricsCollector:
    """性能指标收集器

    收集运行时指标并提供聚合查询。
    支持滑动窗口（默认保留最近 1000 条原始数据）。
    """

    def __init__(self, window_size: int = 1000):
        self._window_size = window_size

        # 原始数据
        self._latencies: deque[float] = deque(maxlen=window_size)
        self._request_timestamps: deque[float] = deque(maxlen=window_size)

        # 计数器
        self._total_requests: int = 0
        self._active_requests: int = 0
        self._completed_requests: int = 0
        self._failed_requests: int = 0
        self._rate_limited_requests: int = 0

        # 并发
        self._peak_concurrency: int = 0
        self._concurrency_samples: deque[int] = deque(maxlen=window_size)

        # LLM
        self._llm_calls_total: int = 0
        self._llm_calls_active: int = 0
        self._llm_tokens_used: int = 0
        self._llm_429_count: int = 0

        # SSE
        self._sse_connections: int = 0
        self._sse_events_queued: int = 0
        self._sse_events_dropped: int = 0

        # 系统
        self._cpu_samples: deque[float] = deque(maxlen=100)
        self._memory_samples: deque[float] = deque(maxlen=100)

        # DB
        self._db_active: int = 0
        self._db_idle: int = 0

        # 快照历史
        self._snapshots: deque[MetricSnapshot] = deque(maxlen=500)

        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 记录请求
    # ------------------------------------------------------------------

    async def record_request(self, latency: float, success: bool = True,
                              is_rate_limited: bool = False) -> None:
        """记录一次请求"""
        async with self._lock:
            now = time.monotonic()
            self._total_requests += 1
            self._request_timestamps.append(now)
            self._latencies.append(latency)

            if success:
                self._completed_requests += 1
            else:
                self._failed_requests += 1
                if is_rate_limited:
                    self._rate_limited_requests += 1

    async def record_request_start(self) -> None:
        """记录请求开始"""
        async with self._lock:
            self._active_requests += 1
            if self._active_requests > self._peak_concurrency:
                self._peak_concurrency = self._active_requests

    async def record_request_end(self) -> None:
        """记录请求结束"""
        async with self._lock:
            self._active_requests -= 1

    # ------------------------------------------------------------------
    # LLM 指标
    # ------------------------------------------------------------------

    async def record_llm_call(self, tokens: int = 0, is_429: bool = False) -> None:
        """记录 LLM 调用"""
        async with self._lock:
            self._llm_calls_total += 1
            self._llm_tokens_used += tokens
            if is_429:
                self._llm_429_count += 1

    async def record_llm_start(self) -> None:
        async with self._lock:
            self._llm_calls_active += 1

    async def record_llm_end(self) -> None:
        async with self._lock:
            self._llm_calls_active -= 1

    # ------------------------------------------------------------------
    # 系统资源
    # ------------------------------------------------------------------

    async def record_cpu(self, cpu_percent: float) -> None:
        """记录 CPU 使用率"""
        async with self._lock:
            self._cpu_samples.append(cpu_percent)

    async def record_memory(self, memory_mb: float) -> None:
        """记录内存使用"""
        async with self._lock:
            self._memory_samples.append(memory_mb)

    # ------------------------------------------------------------------
    # SSE 指标
    # ------------------------------------------------------------------

    async def record_sse_connection(self, delta: int = 1) -> None:
        """SSE 连接数变更"""
        async with self._lock:
            self._sse_connections += delta

    async def record_sse_event(self, queued: bool = True) -> None:
        """SSE 事件"""
        async with self._lock:
            if queued:
                self._sse_events_queued += 1
            else:
                self._sse_events_dropped += 1

    # ------------------------------------------------------------------
    # 连接池
    # ------------------------------------------------------------------

    async def record_db_connections(self, active: int, idle: int) -> None:
        """记录数据库连接数"""
        async with self._lock:
            self._db_active = active
            self._db_idle = idle

    # ------------------------------------------------------------------
    # 快照
    # ------------------------------------------------------------------

    async def capture_snapshot(self, name: str = "") -> MetricSnapshot:
        """捕获当前指标快照"""
        async with self._lock:
            snapshot = MetricSnapshot(
                metric_id=str(uuid.uuid4())[:8],
                name=name or f"snapshot_{len(self._snapshots)}",
                value=float(self._total_requests),
                labels={
                    "active": str(self._active_requests),
                    "completed": str(self._completed_requests),
                    "failed": str(self._failed_requests),
                },
            )
            self._snapshots.append(snapshot)
            return snapshot

    def get_snapshots(self, limit: int = 50) -> list[MetricSnapshot]:
        """获取最近快照"""
        items = list(self._snapshots)
        return items[-limit:]

    # ------------------------------------------------------------------
    # 聚合查询
    # ------------------------------------------------------------------

    def get_snapshot(self) -> PerformanceMetrics:
        """获取当前性能指标汇总"""
        # 延迟统计
        latencies = list(self._latencies)
        lat_avg = statistics.mean(latencies) if latencies else 0.0
        lat_p50 = self._percentile(latencies, 50) if latencies else 0.0
        lat_p95 = self._percentile(latencies, 95) if latencies else 0.0
        lat_p99 = self._percentile(latencies, 99) if latencies else 0.0

        # 吞吐
        now = time.monotonic()
        recent_ts = [t for t in self._request_timestamps if now - t <= 1.0]
        current_rps = len(recent_ts)

        # 平均吞吐
        if self._request_timestamps:
            first = self._request_timestamps[0]
            elapsed = now - first
            avg_rps = len(self._request_timestamps) / elapsed if elapsed > 0 else 0
        else:
            avg_rps = 0.0

        # 峰值吞吐
        peak_rps = max(
            current_rps,
            getattr(self, '_peak_rps', 0.0)
        )
        self._peak_rps = peak_rps  # type: ignore

        # 错误率
        error_rate = self._failed_requests / max(1, self._total_requests)

        # 系统资源
        cpu = statistics.mean(self._cpu_samples) if self._cpu_samples else 0.0
        mem = statistics.mean(self._memory_samples) if self._memory_samples else 0.0

        return PerformanceMetrics(
            total_requests=self._total_requests,
            active_requests=self._active_requests,
            completed_requests=self._completed_requests,
            failed_requests=self._failed_requests,
            rate_limited_requests=self._rate_limited_requests,
            latency_avg=round(lat_avg, 6),
            latency_p50=round(lat_p50, 6),
            latency_p95=round(lat_p95, 6),
            latency_p99=round(lat_p99, 6),
            current_rps=round(current_rps, 2),
            avg_rps=round(avg_rps, 2),
            peak_rps=round(peak_rps, 2),
            error_rate=round(error_rate, 4),
            current_concurrency=self._active_requests,
            peak_concurrency=self._peak_concurrency,
            llm_calls_total=self._llm_calls_total,
            llm_calls_active=self._llm_calls_active,
            llm_tokens_used=self._llm_tokens_used,
            llm_429_count=self._llm_429_count,
            cpu_percent=round(cpu, 1),
            memory_mb=round(mem, 1),
            db_connections_active=self._db_active,
            db_connections_idle=self._db_idle,
            sse_connections=self._sse_connections,
            sse_events_queued=self._sse_events_queued,
            sse_events_dropped=self._sse_events_dropped,
        )

    def get_aggregated(self, metric_name: str,
                        aggregation: MetricsAggregation = MetricsAggregation.AVG,
                        ) -> float:
        """按聚合方式获取指标值"""
        latencies = list(self._latencies)
        if not latencies:
            return 0.0

        if aggregation == MetricsAggregation.AVG:
            return round(statistics.mean(latencies), 6)
        elif aggregation == MetricsAggregation.P50:
            return round(self._percentile(latencies, 50), 6)
        elif aggregation == MetricsAggregation.P95:
            return round(self._percentile(latencies, 95), 6)
        elif aggregation == MetricsAggregation.P99:
            return round(self._percentile(latencies, 99), 6)
        elif aggregation == MetricsAggregation.MAX:
            return round(max(latencies), 6)
        elif aggregation == MetricsAggregation.MIN:
            return round(min(latencies), 6)
        elif aggregation == MetricsAggregation.SUM:
            return round(sum(latencies), 6)
        elif aggregation == MetricsAggregation.COUNT:
            return float(len(latencies))
        return 0.0

    # ------------------------------------------------------------------
    # 重置
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """重置所有指标"""
        self._latencies.clear()
        self._request_timestamps.clear()
        self._total_requests = 0
        self._active_requests = 0
        self._completed_requests = 0
        self._failed_requests = 0
        self._rate_limited_requests = 0
        self._peak_concurrency = 0
        self._concurrency_samples.clear()
        self._llm_calls_total = 0
        self._llm_calls_active = 0
        self._llm_tokens_used = 0
        self._llm_429_count = 0
        self._sse_connections = 0
        self._sse_events_queued = 0
        self._sse_events_dropped = 0
        self._cpu_samples.clear()
        self._memory_samples.clear()
        self._db_active = 0
        self._db_idle = 0
        self._snapshots.clear()

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _percentile(data: list[float], p: float) -> float:
        if not data:
            return 0.0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * p / 100.0
        f = int(k)
        c = k - f
        if f + 1 < len(sorted_data):
            return sorted_data[f] + c * (sorted_data[f + 1] - sorted_data[f])
        return sorted_data[f]
