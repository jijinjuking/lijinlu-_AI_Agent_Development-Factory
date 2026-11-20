"""
Scheduler 数据模型
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.runtime.execution_engine.workflow_schema import WorkflowSpec


class TaskStatus(str, enum.Enum):
    """调度任务状态"""
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


Capability = str  # 如 "code_generation", "browser_control", "deployment"


@dataclass
class ScheduledTask:
    """调度器管理的任务"""
    task_id: str
    capability: Capability
    workflow_spec: WorkflowSpec
    priority: int = 5          # 1(highest)-10(lowest)
    status: TaskStatus = TaskStatus.QUEUED
    metadata: dict[str, Any] = field(default_factory=dict)
    # 调度追踪
    retry_count: int = 0
    dispatched_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    assigned_worker_id: str | None = None
    error_message: str | None = None

    @property
    def age_seconds(self) -> float:
        """任务在队列中的等待时间"""
        if self.dispatched_at is None:
            return 0.0
        return (datetime.now(timezone.utc) - self.dispatched_at).total_seconds()


@dataclass
class WorkerInfo:
    """Worker 注册信息"""
    worker_id: str
    capabilities: list[Capability]
    status: str = "idle"       # idle | busy | unhealthy
    max_concurrency: int = 1
    current_load: int = 0
    last_heartbeat: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        return self.status == "idle" and self.current_load < self.max_concurrency

    @property
    def is_healthy(self) -> bool:
        return self.status != "unhealthy"


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3
    strategy: str = "exponential"   # exponential | linear | fixed
    base_delay: float = 1.0         # 秒
    max_delay: float = 60.0         # 秒
    retryable_errors: set[str] = field(default_factory=lambda: {
        "timeout", "rate_limit", "connection_error", "transient"
    })

    def delay_for(self, attempt: int) -> float:
        if self.strategy == "fixed":
            return self.base_delay
        elif self.strategy == "linear":
            return min(self.base_delay * attempt, self.max_delay)
        else:  # exponential
            return min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)


@dataclass
class TimeoutConfig:
    """超时配置"""
    default_timeout: float = 300.0      # 默认 5 分钟
    per_capability: dict[Capability, float] = field(default_factory=dict)
    timeout_action: str = "cancel"      # cancel | retry

    def timeout_for(self, capability: Capability) -> float:
        return self.per_capability.get(capability, self.default_timeout)


@dataclass
class ScheduleResult:
    """调度执行结果"""
    task_id: str
    status: TaskStatus
    worker_id: str | None = None
    model_name: str | None = None
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration: float = 0.0
    retry_count: int = 0
