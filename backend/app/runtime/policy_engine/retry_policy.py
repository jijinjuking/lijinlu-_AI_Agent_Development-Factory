"""
RetryPolicy — 可配置重试策略（Policy Engine 版本）

支持:
- 指数退避 (exponential): delay = base_delay * 2^(attempt-1)
- 线性递增 (linear): delay = base_delay * attempt
- 固定间隔 (fixed): delay = base_delay

此为 Policy Engine 内的独立副本，与 Scheduler 内的 retry_policy.py 保持兼容。
"""
from __future__ import annotations

import asyncio

from app.runtime.policy_engine.models import RetryConfig


class RetryPolicy:
    """重试策略执行器"""

    def __init__(self, config: RetryConfig | None = None):
        self.config = config or RetryConfig()

    def should_retry(self, error: str, attempt: int) -> bool:
        """判断是否应该重试"""
        if attempt >= self.config.max_retries:
            return False
        for retryable in self.config.retryable_errors:
            if retryable in error.lower():
                return True
        return False

    def delay_seconds(self, attempt: int) -> float:
        """计算当前 attempt 的等待时间"""
        return self.config.delay_for(attempt)

    async def backoff(self, attempt: int, error: str) -> float:
        """执行退避等待，返回等待的秒数"""
        delay = self.delay_seconds(attempt)
        if delay > 0:
            await asyncio.sleep(delay)
        return delay
