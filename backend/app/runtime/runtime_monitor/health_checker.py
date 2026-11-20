"""
Health Checker — 健康检查器

检查各组件健康状态，生成健康报告。
"""

import time
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .models import HealthStatus, HealthReport

logger = logging.getLogger(__name__)


class HealthChecker:
    """健康检查器

    用法:
        checker = HealthChecker()
        checker.register_check("db", lambda: check_db_connection())
        checker.register_check("cache", lambda: check_redis())
        report = await checker.check_all()
    """

    def __init__(self):
        self._checks: Dict[str, Tuple[Callable, float]] = {}
        self._history: List[HealthReport] = []
        self._max_history = 100

    def register_check(self, component: str, check_fn: Callable,
                       timeout_seconds: float = 5.0) -> None:
        """注册健康检查"""
        self._checks[component] = (check_fn, timeout_seconds)

    def unregister_check(self, component: str) -> None:
        """注销健康检查"""
        self._checks.pop(component, None)

    async def check_all(self) -> HealthReport:
        """执行所有健康检查"""
        results = {}
        all_healthy = True
        any_degraded = False

        for component, (check_fn, _) in self._checks.items():
            try:
                import asyncio
                if asyncio.iscoroutinefunction(check_fn):
                    ok = await check_fn()
                else:
                    ok = check_fn()
                results[component] = ok
                if not ok:
                    all_healthy = False
            except Exception as e:
                logger.error(f"Health check failed for {component}: {e}")
                results[component] = False
                all_healthy = False

        # 判断状态
        healthy_count = sum(1 for v in results.values() if v)
        total_count = len(results) if results else 1
        ratio = healthy_count / total_count

        if ratio >= 1.0:
            status = HealthStatus.HEALTHY
        elif ratio >= 0.5:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.UNHEALTHY

        report = HealthReport(
            status=status,
            component="system",
            checks=results,
            timestamp=time.time(),
        )
        self._history.append(report)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        return report

    async def check_component(self, component: str) -> Optional[HealthReport]:
        """检查单个组件"""
        check_entry = self._checks.get(component)
        if not check_entry:
            return None

        check_fn, _ = check_entry
        try:
            ok = await check_fn() if hasattr(check_fn, '__await__') else check_fn()
        except Exception as e:
            ok = False
            logger.error(f"Health check failed for {component}: {e}")

        return HealthReport(
            status=HealthStatus.HEALTHY if ok else HealthStatus.UNHEALTHY,
            component=component,
            checks={component: ok},
            timestamp=time.time(),
        )

    def get_history(self, limit: int = 10) -> List[HealthReport]:
        return self._history[-limit:]

    def get_latest(self) -> Optional[HealthReport]:
        return self._history[-1] if self._history else None

    @property
    def registered_components(self) -> List[str]:
        return list(self._checks.keys())
