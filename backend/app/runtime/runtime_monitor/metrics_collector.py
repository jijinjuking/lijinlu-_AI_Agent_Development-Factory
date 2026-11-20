"""
Metrics Collector — 指标收集器

收集运行时指标，支持 Counter/Gauge/Histogram。
"""

import time
import logging
from collections import defaultdict
from typing import Dict, List, Optional

from .models import Metric, MetricType, RuntimeStats, HealthStatus, HealthReport

logger = logging.getLogger(__name__)


class MetricsCollector:
    """指标收集器"""

    def __init__(self):
        self._metrics: Dict[str, List[Metric]] = defaultdict(list)
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._start_time = time.time()
        self._events: List[dict] = []

    # ---- Metric Recording ----

    def increment(self, name: str, value: float = 1.0, labels: dict = None) -> None:
        """递增计数器"""
        key = self._key(name, labels)
        self._counters[key] += value
        self._record(Metric(
            name=name, type=MetricType.COUNTER,
            value=self._counters[key], labels=labels or {},
        ))

    def gauge(self, name: str, value: float, labels: dict = None) -> None:
        """设置仪表值"""
        key = self._key(name, labels)
        self._gauges[key] = value
        self._record(Metric(
            name=name, type=MetricType.GAUGE,
            value=value, labels=labels or {},
        ))

    def observe(self, name: str, value: float, labels: dict = None) -> None:
        """记录直方图观察值"""
        key = self._key(name, labels)
        self._histograms[key].append(value)
        self._record(Metric(
            name=name, type=MetricType.HISTOGRAM,
            value=value, labels=labels or {},
        ))

    def event(self, event_type: str, data: dict = None) -> None:
        """记录事件"""
        self._events.append({
            "type": event_type,
            "data": data or {},
            "timestamp": time.time(),
        })

    # ---- Reads ----

    def get_counter(self, name: str, labels: dict = None) -> float:
        return self._counters.get(self._key(name, labels), 0.0)

    def get_gauge(self, name: str, labels: dict = None) -> float:
        return self._gauges.get(self._key(name, labels), 0.0)

    def get_histogram_stats(self, name: str, labels: dict = None) -> dict:
        values = self._histograms.get(self._key(name, labels), [])
        if not values:
            return {"count": 0, "sum": 0, "avg": 0, "min": 0, "max": 0, "p50": 0, "p95": 0, "p99": 0}
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        return {
            "count": n,
            "sum": sum(sorted_vals),
            "avg": sum(sorted_vals) / n,
            "min": sorted_vals[0],
            "max": sorted_vals[-1],
            "p50": sorted_vals[int(n * 0.5)],
            "p95": sorted_vals[int(n * 0.95)],
            "p99": sorted_vals[int(n * 0.99)],
        }

    def get_stats(self) -> RuntimeStats:
        """获取运行时统计"""
        return RuntimeStats(
            active_tasks=int(self.get_gauge("tasks.active")),
            completed_tasks=int(self.get_counter("tasks.completed")),
            failed_tasks=int(self.get_counter("tasks.failed")),
            total_iterations=int(self.get_counter("iterations.total")),
            loop_detections=int(self.get_counter("loop.detections")),
            recoveries_attempted=int(self.get_counter("recovery.attempted")),
            recoveries_succeeded=int(self.get_counter("recovery.succeeded")),
            sandbox_executions=int(self.get_counter("sandbox.executions")),
            sandbox_failures=int(self.get_counter("sandbox.failures")),
            uptime_seconds=time.time() - self._start_time,
            metrics={
                "avg_execution_time": self.get_histogram_stats("execution.duration").get("avg", 0),
                "error_rate": self._calc_error_rate(),
                "load_avg": self.get_gauge("system.load_avg"),
                "queue_depth": self.get_gauge("queue.depth"),
            },
        )

    def _calc_error_rate(self) -> float:
        completed = self.get_counter("tasks.completed")
        failed = self.get_counter("tasks.failed")
        total = completed + failed
        if total == 0:
            return 0.0
        return failed / total

    # ---- Internal ----

    def _key(self, name: str, labels: dict = None) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def _record(self, metric: Metric) -> None:
        self._metrics[metric.name].append(metric)
        # 只保留最近 1000 条
        if len(self._metrics[metric.name]) > 1000:
            self._metrics[metric.name] = self._metrics[metric.name][-500:]
