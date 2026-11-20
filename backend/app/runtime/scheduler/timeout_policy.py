"""
TimeoutPolicy — 超时控制

支持:
- 全局超时: default_timeout
- 按 capability 超时: per_capability
- 超时动作: cancel（取消）| retry（重试）
"""
from __future__ import annotations

import asyncio
from typing import Optional

from app.runtime.scheduler.models import TimeoutConfig, Capability


class TimeoutPolicy:
    """超时策略执行器"""

    def __init__(self, config: TimeoutConfig | None = None):
        self.config = config or TimeoutConfig()

    def timeout_seconds(self, capability: Capability) -> float:
        """返回某能力的超时秒数"""
        return self.config.timeout_for(capability)

    @property
    def timeout_action(self) -> str:
        return self.config.timeout_action

    async def with_timeout(
        self,
        coro,
        capability: Capability,
        *args,
        **kwargs,
    ) -> tuple[Optional[object], bool, Optional[Exception]]:
        """
        带超时执行协程。
        返回 (result, timed_out, error)
        """
        timeout = self.timeout_seconds(capability)
        try:
            result = await asyncio.wait_for(
                coro(*args, **kwargs),
                timeout=timeout,
            )
            return result, False, None
        except asyncio.TimeoutError:
            return None, True, None
        except asyncio.CancelledError:
            return None, False, asyncio.CancelledError()
        except Exception as e:
            return None, False, e
