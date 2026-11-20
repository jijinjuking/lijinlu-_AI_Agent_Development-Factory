"""
TokenBudget — Token 配额管理与消耗追踪

职责:
- 单次请求 Token 检查
- 单任务 Token 累计跟踪
- 每日 Token 配额控制
- 超配额自动警告/暂停
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.runtime.policy_engine.models import (
    TokenBudgetConfig,
    TokenUsage,
    PolicyDecision,
    PolicyResult,
)


class TokenBudget:
    """Token 配额管理器"""

    def __init__(self, config: TokenBudgetConfig | None = None):
        self.config = config or TokenBudgetConfig()
        self._daily_usage: dict[str, int] = {}       # date_key → total_tokens
        self._task_usage: dict[str, int] = {}         # task_id → total_tokens
        self._usage_history: list[TokenUsage] = []    # 全量使用记录

    # ── 检查 ───────────────────────────────────────────

    def check_request(self, estimated_tokens: int, task_id: str) -> PolicyResult:
        """检查单次请求是否通过 Token 配额"""
        checks: dict[str, bool] = {}
        violations: list[str] = []
        warnings: list[str] = []

        # 1. 单次请求限制
        if estimated_tokens > self.config.per_request_limit:
            violations.append(
                f"请求预估 {estimated_tokens} tokens，超过单次上限 {self.config.per_request_limit}"
            )
            checks["per_request"] = False
        else:
            checks["per_request"] = True

        # 2. 单任务累计限制
        task_tokens = self._task_usage.get(task_id, 0) + estimated_tokens
        if task_tokens > self.config.per_task_limit:
            violations.append(
                f"任务累计将达 {task_tokens} tokens，超过单任务上限 {self.config.per_task_limit}"
            )
            checks["per_task"] = False
        else:
            checks["per_task"] = True

        # 3. 每日配额限制
        today_key = self._today_key()
        daily_tokens = self._daily_usage.get(today_key, 0) + estimated_tokens
        if self.config.auto_pause and daily_tokens >= self.config.daily_limit * self.config.pause_threshold:
            violations.append(
                f"日配额将达 {daily_tokens}/{self.config.daily_limit} tokens，触发暂停"
            )
            checks["daily"] = False
        elif daily_tokens >= self.config.daily_limit:
            violations.append(
                f"日配额超限 {daily_tokens}/{self.config.daily_limit} tokens"
            )
            checks["daily"] = False
        elif daily_tokens >= self.config.daily_limit * self.config.warning_threshold:
            warnings.append(
                f"日配额使用 {daily_tokens}/{self.config.daily_limit} tokens，超过警告阈值"
            )
            checks["daily"] = True
        else:
            checks["daily"] = True

        # 判定
        if any(not v for v in checks.values()):
            return PolicyResult(
                decision=PolicyDecision.PAUSE if self.config.auto_pause else PolicyDecision.DENY,
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

    def check_remaining(self, task_id: str) -> PolicyResult:
        """查询当前剩余配额"""
        today_key = self._today_key()
        daily_used = self._daily_usage.get(today_key, 0)
        task_used = self._task_usage.get(task_id, 0)

        daily_pct = daily_used / max(self.config.daily_limit, 1)
        task_pct = task_used / max(self.config.per_task_limit, 1)

        if daily_pct >= self.config.pause_threshold or task_pct >= 1.0:
            return PolicyResult(
                decision=PolicyDecision.PAUSE,
                reason=f"日配额 {daily_pct:.0%}，任务配额 {task_pct:.0%}",
                metadata={"daily_used": daily_used, "task_used": task_used},
            )
        return PolicyResult(
            decision=PolicyDecision.ALLOW,
            metadata={"daily_used": daily_used, "task_used": task_used, "daily_pct": daily_pct},
        )

    # ── 记录消耗 ───────────────────────────────────────

    def record_usage(self, usage: TokenUsage):
        """记录一次 Token 消耗"""
        today_key = self._today_key()
        self._daily_usage[today_key] = self._daily_usage.get(today_key, 0) + usage.total_tokens
        self._task_usage[usage.task_id] = self._task_usage.get(usage.task_id, 0) + usage.total_tokens
        self._usage_history.append(usage)

    # ── 查询 ───────────────────────────────────────────

    def daily_used(self) -> int:
        return self._daily_usage.get(self._today_key(), 0)

    def task_used(self, task_id: str) -> int:
        return self._task_usage.get(task_id, 0)

    def daily_limit(self) -> int:
        return self.config.daily_limit

    def per_task_limit(self) -> int:
        return self.config.per_task_limit

    def usage_history(self, task_id: Optional[str] = None) -> list[TokenUsage]:
        """获取使用历史，可按 task_id 过滤"""
        if task_id:
            return [u for u in self._usage_history if u.task_id == task_id]
        return list(self._usage_history)

    # ── 管理 ───────────────────────────────────────────

    def reset_daily(self):
        """重置每日计数"""
        self._daily_usage.pop(self._today_key(), None)

    def reset_task(self, task_id: str):
        """重置任务计数"""
        self._task_usage.pop(task_id, None)

    def reset_all(self):
        """重置所有计数"""
        self._daily_usage.clear()
        self._task_usage.clear()
        self._usage_history.clear()

    # ── 内部 ───────────────────────────────────────────

    @staticmethod
    def _today_key() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
