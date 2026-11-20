"""
CostControl — 费用预算管理与强制执行

职责:
- 费用追踪（记录每次 LLM 调用的费用）
- 日/月预算检查
- 超预算自动暂停
- 费用统计查询
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.runtime.policy_engine.models import (
    CostBudgetConfig,
    CostRecord,
    PolicyDecision,
    PolicyResult,
)


# 模型定价表 ($/1K tokens)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"prompt": 0.0025, "completion": 0.01},
    "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
    "gpt-4-turbo": {"prompt": 0.01, "completion": 0.03},
    "gpt-3.5-turbo": {"prompt": 0.0005, "completion": 0.0015},
    "claude-3.5-sonnet": {"prompt": 0.003, "completion": 0.015},
    "claude-3-haiku": {"prompt": 0.00025, "completion": 0.00125},
    "qwen2.5": {"prompt": 0.0, "completion": 0.0},
    "deepseek-chat": {"prompt": 0.00014, "completion": 0.00028},
    "unknown": {"prompt": 0.001, "completion": 0.002},
}


class CostControl:
    """费用预算控制器"""

    def __init__(self, config: CostBudgetConfig | None = None):
        self.config = config or CostBudgetConfig()
        self._records: list[CostRecord] = []

    # ── 费用计算 ───────────────────────────────────────

    @staticmethod
    def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """计算单次调用的费用（USD）"""
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["unknown"])
        return (prompt_tokens / 1000 * pricing["prompt"] +
                completion_tokens / 1000 * pricing["completion"])

    # ── 预算检查 ───────────────────────────────────────

    def check_budget(self, estimated_cost_usd: float, task_id: str) -> PolicyResult:
        """检查预算是否允许本次调用"""
        checks: dict[str, bool] = {}
        violations: list[str] = []
        warnings: list[str] = []

        today_cost = self._cost_in_period("day") + estimated_cost_usd
        month_cost = self._cost_in_period("month") + estimated_cost_usd

        # 日预算检查
        daily_ok = self._check_budget_level(
            cost=today_cost,
            budget=self.config.daily_budget_usd,
            warning_threshold=self.config.warning_threshold,
            pause_threshold=self.config.pause_threshold,
            auto_pause=self.config.auto_pause,
            label="日",
            violations=violations,
            warnings=warnings,
        )
        checks["daily"] = daily_ok

        # 月预算检查
        monthly_ok = self._check_budget_level(
            cost=month_cost,
            budget=self.config.monthly_budget_usd,
            warning_threshold=self.config.warning_threshold,
            pause_threshold=self.config.pause_threshold,
            auto_pause=self.config.auto_pause,
            label="月",
            violations=violations,
            warnings=warnings,
        )
        checks["monthly"] = monthly_ok

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

    # ── 费用记录 ───────────────────────────────────────

    def record_cost(self, record: CostRecord):
        """记录一次费用"""
        self._records.append(record)

    def record_call(
        self,
        task_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> CostRecord:
        """便捷方法：记录调用并返回 CostRecord"""
        cost = self.calculate_cost(model, prompt_tokens, completion_tokens)
        record = CostRecord(
            task_id=task_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
        )
        self._records.append(record)
        return record

    # ── 查询 ───────────────────────────────────────────

    def total_cost(self) -> float:
        """总费用"""
        return sum(r.cost_usd for r in self._records)

    def cost_for_task(self, task_id: str) -> float:
        return sum(r.cost_usd for r in self._records if r.task_id == task_id)

    def daily_cost(self) -> float:
        return self._cost_in_period("day")

    def monthly_cost(self) -> float:
        return self._cost_in_period("month")

    def records(self, task_id: Optional[str] = None) -> list[CostRecord]:
        """获取费用记录"""
        if task_id:
            return [r for r in self._records if r.task_id == task_id]
        return list(self._records)

    # ── 管理 ───────────────────────────────────────────

    def reset_all(self):
        self._records.clear()

    # ── 内部 ───────────────────────────────────────────

    def _cost_in_period(self, period: str) -> float:
        """统计某个时间段的累计费用"""
        now = datetime.now(timezone.utc)
        if period == "day":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "month":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            return 0.0
        return sum(r.cost_usd for r in self._records if r.timestamp >= start)

    @staticmethod
    def _check_budget_level(
        cost: float,
        budget: float,
        warning_threshold: float,
        pause_threshold: float,
        auto_pause: bool,
        label: str,
        violations: list[str],
        warnings: list[str],
    ) -> bool:
        """
        单层预算检查逻辑。
        返回 True 表示通过，False 表示未通过。
        检查顺序：auto-pause → exceeded → warning → ok
        """
        # 1. Auto-pause（仅在启用时）
        if auto_pause and cost >= budget * pause_threshold:
            violations.append(
                f"{label}累计 ${cost:.4f}，将超过{label}预算 ${budget:.2f}，触发暂停"
            )
            return False
        # 2. 超过预算
        if cost >= budget:
            violations.append(
                f"{label}累计 ${cost:.4f}，超过{label}预算 ${budget:.2f}"
            )
            return False
        # 3. 超过警告线
        if cost >= budget * warning_threshold:
            warnings.append(
                f"{label}累计 ${cost:.4f}，超过{label}预算警告线 ${budget * warning_threshold:.2f}"
            )
        return True
