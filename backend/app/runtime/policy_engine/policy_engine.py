"""
PolicyEngine — 统一治理引擎

职责:
- 编排全部子引擎：Token + Cost + Permission + Retry + Timeout + Audit
- 提供统一 check() 接口：执行前一站式策略检查
- 记录所有决策结果到审计日志
- 发送策略事件到 EventBus（如果有）
"""
from __future__ import annotations

from typing import Optional

from app.runtime.policy_engine.models import (
    TokenBudgetConfig,
    CostBudgetConfig,
    RetryConfig,
    TimeoutConfig,
    TokenUsage,
    CostRecord,
    Role,
    PermissionAction,
    PermissionResource,
    PolicyDecision,
    PolicyResult,
    AuditAction,
)
from app.runtime.policy_engine.token_budget import TokenBudget
from app.runtime.policy_engine.cost_control import CostControl
from app.runtime.policy_engine.permission_engine import PermissionEngine
from app.runtime.policy_engine.audit_logger import AuditLogger
from app.runtime.policy_engine.retry_policy import RetryPolicy
from app.runtime.policy_engine.timeout_policy import TimeoutPolicy
from app.runtime.scheduler.models import Capability


class PolicyEngine:
    """
    统一策略引擎。

    使用方式:
        engine = PolicyEngine()
        result = engine.check(
            task_id="task-1",
            role_names=["developer"],
            action=PermissionAction.EXECUTE,
            resource=PermissionResource.AGENT,
            estimated_tokens=2000,
            estimated_cost_usd=0.01,
        )
        if not result.allowed:
            raise PermissionError(result.reason)
        # 继续执行...
    """

    def __init__(
        self,
        token_config: TokenBudgetConfig | None = None,
        cost_config: CostBudgetConfig | None = None,
        retry_config: RetryConfig | None = None,
        timeout_config: TimeoutConfig | None = None,
        roles: dict[str, Role] | None = None,
        event_bus=None,
    ):
        self.token_budget = TokenBudget(token_config)
        self.cost_control = CostControl(cost_config)
        self.permission = PermissionEngine(roles)
        self.audit = AuditLogger()
        self.retry = RetryPolicy(retry_config)
        self.timeout = TimeoutPolicy(timeout_config)
        self._event_bus = event_bus

    # ── 统一检查 ───────────────────────────────────────

    def check(
        self,
        task_id: str,
        role_names: list[str],
        action: PermissionAction,
        resource: PermissionResource,
        resource_id: Optional[str] = None,
        estimated_tokens: int = 0,
        model: str = "unknown",
    ) -> PolicyResult:
        """
        一站式策略检查：Permission → Token → Cost。

        返回 PolicyResult，包含每项检查的通过/失败状态。
        """
        checks: dict[str, bool] = {}
        violations: list[str] = []
        warnings: list[str] = []

        # 1. 权限检查
        perm_result = self.permission.check(role_names, action, resource, resource_id)
        checks["permission"] = perm_result.allowed
        if not perm_result.allowed:
            violations.append(perm_result.reason)
            self.audit.log_permission_denied(
                task_id, ",".join(role_names), action.value,
                f"{resource.value}:{resource_id or '*'}"
            )

        # 2. Token 配额检查
        if estimated_tokens > 0:
            token_result = self.token_budget.check_request(estimated_tokens, task_id)
            checks["token_budget"] = token_result.allowed
            if not token_result.allowed:
                violations.extend(token_result.violations)
                self.audit.log_budget_exceeded(
                    task_id, "token",
                    self.token_budget.daily_limit(),
                    self.token_budget.daily_used() + estimated_tokens,
                )
            if token_result.warnings:
                warnings.extend(token_result.warnings)
        else:
            checks["token_budget"] = True

        # 3. 费用预算检查
        if model != "unknown" and estimated_tokens > 0:
            cost = self.cost_control.calculate_cost(model, estimated_tokens, 0)
            cost_result = self.cost_control.check_budget(cost, task_id)
            checks["cost_budget"] = cost_result.allowed
            if not cost_result.allowed:
                violations.extend(cost_result.violations)
                self.audit.log_budget_exceeded(
                    task_id, "cost",
                    self.cost_control.config.daily_budget_usd,
                    self.cost_control.daily_cost() + cost,
                )
            if cost_result.warnings:
                warnings.extend(cost_result.warnings)
        else:
            checks["cost_budget"] = True

        # 判定最终决策
        if violations:
            self.audit.log_policy_violation(
                task_id,
                "; ".join(violations),
                checks=checks,
            )
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason="; ".join(violations),
                checks=checks,
                violations=violations,
                warnings=warnings,
            )
        if warnings:
            return PolicyResult(
                decision=PolicyDecision.WARN,
                reason="; ".join(warnings),
                checks=checks,
                warnings=warnings,
            )
        return PolicyResult(decision=PolicyDecision.ALLOW, checks=checks)

    def check_permission_only(
        self,
        role_names: list[str],
        action: PermissionAction,
        resource: PermissionResource,
        resource_id: Optional[str] = None,
    ) -> PolicyResult:
        """只检查权限"""
        return self.permission.check(role_names, action, resource, resource_id)

    def check_budget_only(
        self,
        task_id: str,
        estimated_tokens: int,
        model: str = "unknown",
    ) -> PolicyResult:
        """只检查预算（Token + Cost）"""
        token_result = self.token_budget.check_request(estimated_tokens, task_id)
        cost = self.cost_control.calculate_cost(model, estimated_tokens, 0)
        cost_result = self.cost_control.check_budget(cost, task_id)

        violations = token_result.violations + cost_result.violations
        warnings = token_result.warnings + cost_result.warnings
        checks = {"token_budget": token_result.allowed, "cost_budget": cost_result.allowed}

        if violations:
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason="; ".join(violations),
                checks=checks,
                violations=violations,
            )
        if warnings:
            return PolicyResult(
                decision=PolicyDecision.WARN,
                reason="; ".join(warnings),
                checks=checks,
                warnings=warnings,
            )
        return PolicyResult(decision=PolicyDecision.ALLOW, checks=checks)

    # ── 记录 ───────────────────────────────────────────

    def record_token_usage(self, usage: TokenUsage):
        """记录 Token 消耗"""
        self.token_budget.record_usage(usage)
        self.audit.log_action(
            AuditAction.TOOL_EXECUTED,
            task_id=usage.task_id,
            model=usage.model,
            tokens=usage.total_tokens,
        )

    def record_cost(self, record: CostRecord):
        """记录费用"""
        self.cost_control.record_cost(record)

    # ── 统计 ───────────────────────────────────────────

    def stats(self) -> dict:
        """引擎统计摘要"""
        return {
            "token": {
                "daily_used": self.token_budget.daily_used(),
                "daily_limit": self.token_budget.daily_limit(),
                "usage_pct": self.token_budget.daily_used() / max(self.token_budget.daily_limit(), 1),
            },
            "cost": {
                "daily_cost": self.cost_control.daily_cost(),
                "monthly_cost": self.cost_control.monthly_cost(),
                "total_cost": self.cost_control.total_cost(),
            },
            "audit": {
                "total_entries": self.audit.count,
                "violations": self.audit.violation_count(),
            },
        }

    # ── 管理 ───────────────────────────────────────────

    def reset_all(self):
        """重置所有计数器"""
        self.token_budget.reset_all()
        self.cost_control.reset_all()
        self.audit.clear()
