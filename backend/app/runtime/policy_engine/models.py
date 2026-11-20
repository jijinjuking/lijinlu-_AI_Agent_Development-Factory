"""
Policy Engine 数据模型

覆盖:
- Token Budget: 配额配置、消耗记录
- Cost Control: 预算配置、费用记录
- Permission: 角色/权限定义
- Audit: 审计日志条目
- Policy Result: 策略检查结果
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ── Token Budget ──────────────────────────────────────────────

@dataclass
class TokenBudgetConfig:
    """Token 配额配置"""
    daily_limit: int = 100_000           # 每日 Token 上限
    per_task_limit: int = 20_000         # 单任务 Token 上限
    per_request_limit: int = 8_000       # 单次请求 Token 上限
    warning_threshold: float = 0.8       # 警告阈值（80% 触发告警）
    auto_pause: bool = True              # 超配额自动暂停
    pause_threshold: float = 0.95        # 暂停阈值（95% 触发暂停）


@dataclass
class TokenUsage:
    """Token 消耗记录"""
    task_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = "unknown"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


# ── Cost Control ──────────────────────────────────────────────

@dataclass
class CostBudgetConfig:
    """费用预算配置"""
    daily_budget_usd: float = 10.0       # 每日预算（美元）
    monthly_budget_usd: float = 200.0    # 月预算
    warning_threshold: float = 0.8       # 警告阈值
    auto_pause: bool = True              # 超预算自动暂停
    pause_threshold: float = 0.95        # 暂停阈值


@dataclass
class CostRecord:
    """单次调用费用记录"""
    task_id: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Permission ────────────────────────────────────────────────

class PermissionAction(str, enum.Enum):
    """权限操作类型"""
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    DELETE = "delete"
    MANAGE = "manage"


class PermissionResource(str, enum.Enum):
    """权限资源类型"""
    AGENT = "agent"
    TOOL = "tool"
    ARTIFACT = "artifact"
    TASK = "task"
    WORKFLOW = "workflow"
    POLICY = "policy"


@dataclass
class Permission:
    """单条权限规则"""
    action: PermissionAction
    resource: PermissionResource
    resource_id: str | None = None   # None = 该类型所有资源
    effect: str = "allow"            # allow | deny


@dataclass
class Role:
    """角色定义"""
    name: str
    permissions: list[Permission] = field(default_factory=list)
    priority: int = 0                # 数字越大优先级越高


# ── Audit ─────────────────────────────────────────────────────

class AuditAction(str, enum.Enum):
    """审计操作类型"""
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    POLICY_VIOLATION = "policy_violation"
    BUDGET_EXCEEDED = "budget_exceeded"
    PERMISSION_DENIED = "permission_denied"
    TOOL_EXECUTED = "tool_executed"
    AGENT_INVOKED = "agent_invoked"


@dataclass
class AuditEntry:
    """审计日志条目"""
    action: AuditAction
    task_id: str | None = None
    actor: str = "system"
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Policy Result ─────────────────────────────────────────────

class PolicyDecision(str, enum.Enum):
    """策略决策"""
    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"
    PAUSE = "pause"


@dataclass
class PolicyResult:
    """策略检查结果"""
    decision: PolicyDecision
    reason: str = ""
    checks: dict[str, bool] = field(default_factory=dict)  # 各检查项结果
    violations: list[str] = field(default_factory=list)     # 违规列表
    warnings: list[str] = field(default_factory=list)       # 警告列表
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision in (PolicyDecision.ALLOW, PolicyDecision.WARN)


# ── Retry & Timeout (来自 Scheduler，Policy Engine 副本) ──────

Capability = str  # 如 "code_generation", "browser_control"


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
