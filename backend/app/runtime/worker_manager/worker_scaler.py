"""
Worker Scaler — 自动扩缩容

根据负载指标自动决定扩缩容。
"""

import asyncio
import logging
import time
from typing import Callable, Dict, List, Optional

from .models import ScalingRule, ScalingDecision, ScalingDirection
from .worker_registry import WorkerRegistry

logger = logging.getLogger(__name__)


class WorkerScaler:
    """自动扩缩容"""

    def __init__(self, registry: WorkerRegistry, rules: List[ScalingRule] = None):
        self.registry = registry
        self.rules: Dict[str, ScalingRule] = {}
        if rules:
            for r in rules:
                self.rules[r.metric] = r
        self._last_scale_time: Dict[str, float] = {}
        self._scale_handlers: Dict[ScalingDirection, List[Callable]] = {
            ScalingDirection.UP: [],
            ScalingDirection.DOWN: [],
        }

    def add_rule(self, rule: ScalingRule) -> None:
        """添加扩缩容规则"""
        self.rules[rule.metric] = rule

    def on_scale(self, direction: ScalingDirection, handler: Callable) -> None:
        """注册扩缩容回调"""
        self._scale_handlers[direction].append(handler)

    async def evaluate(self, metrics: Dict[str, float]) -> Optional[ScalingDecision]:
        """
        评估扩缩容。

        metrics: {"load_avg": 0.8, "queue_depth": 50, "error_rate": 0.02}
        """
        for metric_name, value in metrics.items():
            rule = self.rules.get(metric_name)
            if not rule:
                continue

            # 检查冷却时间
            now = time.time()
            last_scale = self._last_scale_time.get(metric_name, 0)
            if now - last_scale < rule.cooldown_seconds:
                continue

            # 扩容
            if value >= rule.threshold_up:
                current = self.registry.online_count
                if current < rule.max_workers:
                    decision = ScalingDecision(
                        direction=ScalingDirection.UP,
                        count=min(rule.scale_step, rule.max_workers - current),
                        reason=f"{metric_name}={value} >= threshold_up={rule.threshold_up}",
                    )
                    await self._execute_scaling(decision)
                    self._last_scale_time[metric_name] = now
                    return decision

            # 缩容
            elif value <= rule.threshold_down:
                current = self.registry.online_count
                if current > rule.min_workers:
                    decision = ScalingDecision(
                        direction=ScalingDirection.DOWN,
                        count=min(rule.scale_step, current - rule.min_workers),
                        reason=f"{metric_name}={value} <= threshold_down={rule.threshold_down}",
                    )
                    await self._execute_scaling(decision)
                    self._last_scale_time[metric_name] = now
                    return decision

        return None

    async def _execute_scaling(self, decision: ScalingDecision) -> None:
        """执行扩缩容"""
        logger.info(f"Scaling {decision.direction.value}: {decision.count} workers ({decision.reason})")
        handlers = self._scale_handlers.get(decision.direction, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(decision)
                else:
                    handler(decision)
            except Exception as e:
                logger.error(f"Scale handler failed: {e}")
