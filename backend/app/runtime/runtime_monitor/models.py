"""
Runtime Monitor — Data Models
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import time


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class Metric:
    """监控指标"""
    name: str
    type: MetricType
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class HealthReport:
    """健康报告"""
    status: HealthStatus
    component: str
    message: str = ""
    checks: Dict[str, bool] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class RuntimeStats:
    """运行时统计"""
    total_tasks: int = 0
    active_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    avg_execution_time: float = 0.0
    total_iterations: int = 0
    loop_detections: int = 0
    recoveries_attempted: int = 0
    recoveries_succeeded: int = 0
    sandbox_executions: int = 0
    sandbox_failures: int = 0
    uptime_seconds: float = 0.0
    metrics: Dict[str, float] = field(default_factory=dict)
