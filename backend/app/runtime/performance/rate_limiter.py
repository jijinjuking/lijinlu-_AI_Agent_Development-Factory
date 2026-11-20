"""W35-36 Performance Optimization — API 限流器

RateLimiter 提供多层级的请求限流能力：
- Token Bucket 算法：平滑速率限制，支持突发
- Sliding Window 算法：精确时间窗口计数
- 多作用域：Global / Per-Tenant / Per-User / Per-IP / Per-Endpoint
- FastAPI 中间件集成

使用方式：
    limiter = RateLimiter()
    limiter.add_rule(RateLimitRule(rate=100, burst=200, scope=LimitScope.GLOBAL))
    result = await limiter.check("default", scope_value="")
    if not result.allowed:
        raise HTTPException(429, detail="Rate limited")
"""

import asyncio
import time
from typing import Optional
from collections import defaultdict

from .models import (
    RateLimitRule, RateLimitResult, RateLimitStatus,
    RateLimitAlgorithm, LimitScope
)


class TokenBucket:
    """令牌桶实现

    以恒定速率生成令牌，桶满时丢弃多余令牌。
    每次请求消费一个令牌，无令牌时拒绝。
    """

    def __init__(self, rate: float, burst: float):
        self.rate = rate          # 令牌/秒
        self.burst = burst        # 桶容量
        self._tokens = burst      # 当前令牌数
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def _refill(self) -> None:
        """补充令牌"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * self.rate
        if new_tokens > 0:
            self._tokens = min(self.burst, self._tokens + new_tokens)
            self._last_refill = now

    async def consume(self, tokens: int = 1) -> bool:
        """尝试消费令牌"""
        async with self._lock:
            await self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    @property
    def available_tokens(self) -> float:
        """当前可用令牌数（非异步快照）"""
        return self._tokens

    def reset_at(self) -> float:
        """预计桶满时间（秒后）"""
        deficit = self.burst - self._tokens
        if deficit <= 0:
            return 0.0
        return deficit / self.rate


class SlidingWindow:
    """滑动窗口计数器

    记录时间窗口内的请求时间戳，滑动窗口大小内统计请求数。
    """

    def __init__(self, window_sec: float, max_requests: int):
        self.window_sec = window_sec
        self.max_requests = max_requests
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def record_and_check(self) -> bool:
        """记录一次请求并检查是否超限"""
        async with self._lock:
            now = time.monotonic()
            cutoff = now - self.window_sec
            # 清理过期时间戳
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            if len(self._timestamps) < self.max_requests:
                self._timestamps.append(now)
                return True
            return False

    @property
    def current_count(self) -> int:
        """当前窗口内请求数（非异步快照）"""
        return len(self._timestamps)


class RateLimiter:
    """多层限流器

    管理多个限流规则，按作用域分组。
    请求需通过所有匹配规则的检查。

    使用方式：
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(
            rule_id="global-api",
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            scope=LimitScope.GLOBAL,
            rate=100, burst=200
        ))
        result = await limiter.check("global-api")
    """

    def __init__(self):
        self._rules: dict[str, RateLimitRule] = {}
        self._buckets: dict[str, dict[str, TokenBucket]] = defaultdict(dict)
        self._windows: dict[str, dict[str, SlidingWindow]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 规则管理
    # ------------------------------------------------------------------

    def add_rule(self, rule: RateLimitRule) -> None:
        """添加限流规则"""
        self._rules[rule.rule_id] = rule

    def remove_rule(self, rule_id: str) -> bool:
        """移除限流规则"""
        if rule_id in self._rules:
            del self._rules[rule_id]
            # 清理关联的桶/窗口
            self._buckets.pop(rule_id, None)
            self._windows.pop(rule_id, None)
            return True
        return False

    def get_rule(self, rule_id: str) -> Optional[RateLimitRule]:
        """获取规则"""
        return self._rules.get(rule_id)

    def list_rules(self) -> list[RateLimitRule]:
        """列出所有规则"""
        return list(self._rules.values())

    def update_rule(self, rule_id: str, **kwargs) -> bool:
        """更新规则参数"""
        if rule_id not in self._rules:
            return False
        rule = self._rules[rule_id]
        for k, v in kwargs.items():
            if hasattr(rule, k):
                setattr(rule, k, v)
        # 清除缓存让下次重建
        self._buckets.pop(rule_id, None)
        self._windows.pop(rule_id, None)
        return True

    # ------------------------------------------------------------------
    # 限流检查
    # ------------------------------------------------------------------

    def _build_scope_key(self, rule: RateLimitRule, scope_value: str) -> str:
        """构建作用域键"""
        if rule.scope == LimitScope.GLOBAL:
            return "__global__"
        return scope_value or "__default__"

    async def check(self, rule_id: str, scope_value: str = "",
                    tokens: int = 1) -> RateLimitResult:
        """检查请求是否被限流

        Args:
            rule_id: 规则 ID
            scope_value: 作用域值（如 tenant_id, user_id, ip）
            tokens: 本次消费令牌数

        Returns:
            RateLimitResult: 限流判定结果
        """
        rule = self._rules.get(rule_id)
        if not rule or not rule.enabled:
            return RateLimitResult(
                allowed=True,
                status=RateLimitStatus.ALLOWED,
                rule_id=rule_id,
                reason="no matching rule or disabled"
            )

        scope_key = self._build_scope_key(rule, scope_value)

        if rule.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
            return await self._check_token_bucket(rule, scope_key, tokens)
        elif rule.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
            return await self._check_sliding_window(rule, scope_key)
        else:
            # Fallback: token bucket
            return await self._check_token_bucket(rule, scope_key, tokens)

    async def _check_token_bucket(self, rule: RateLimitRule,
                                   scope_key: str, tokens: int) -> RateLimitResult:
        """令牌桶检查"""
        if scope_key not in self._buckets[rule.rule_id]:
            self._buckets[rule.rule_id][scope_key] = TokenBucket(
                rate=rule.rate, burst=rule.burst
            )

        bucket = self._buckets[rule.rule_id][scope_key]
        allowed = await bucket.consume(tokens)

        remaining = int(bucket.available_tokens)
        retry_after = bucket.reset_at() if rule.retry_after_header else 0.0

        if allowed:
            return RateLimitResult(
                allowed=True,
                status=RateLimitStatus.ALLOWED,
                remaining=remaining,
                limit=int(rule.burst),
                rule_id=rule.rule_id,
            )
        elif rule.queue_on_limit:
            return RateLimitResult(
                allowed=False,
                status=RateLimitStatus.QUEUED,
                remaining=0,
                limit=int(rule.burst),
                retry_after_sec=retry_after,
                rule_id=rule.rule_id,
                reason="rate limited, queued"
            )
        else:
            return RateLimitResult(
                allowed=False,
                status=RateLimitStatus.RATE_LIMITED,
                remaining=0,
                limit=int(rule.burst),
                retry_after_sec=retry_after,
                rule_id=rule.rule_id,
                reason="rate limit exceeded"
            )

    async def _check_sliding_window(self, rule: RateLimitRule,
                                     scope_key: str) -> RateLimitResult:
        """滑动窗口检查"""
        if scope_key not in self._windows[rule.rule_id]:
            self._windows[rule.rule_id][scope_key] = SlidingWindow(
                window_sec=rule.window_sec,
                max_requests=rule.max_requests,
            )

        window = self._windows[rule.rule_id][scope_key]
        allowed = await window.record_and_check()
        remaining = rule.max_requests - window.current_count

        if allowed:
            return RateLimitResult(
                allowed=True,
                status=RateLimitStatus.ALLOWED,
                remaining=max(0, remaining),
                limit=rule.max_requests,
                rule_id=rule.rule_id,
            )
        else:
            return RateLimitResult(
                allowed=False,
                status=RateLimitStatus.RATE_LIMITED,
                remaining=0,
                limit=rule.max_requests,
                retry_after_sec=rule.window_sec,
                rule_id=rule.rule_id,
                reason="rate limit exceeded (sliding window)"
            )

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_bucket_stats(self, rule_id: str, scope_value: str = "") -> dict:
        """获取令牌桶状态"""
        rule = self._rules.get(rule_id)
        if not rule:
            return {}
        scope_key = self._build_scope_key(rule, scope_value)
        bucket = self._buckets.get(rule_id, {}).get(scope_key)
        if not bucket:
            return {}
        return {
            "available_tokens": bucket.available_tokens,
            "rate": bucket.rate,
            "burst": bucket.burst,
            "refill_sec": bucket.reset_at(),
        }

    def get_window_stats(self, rule_id: str, scope_value: str = "") -> dict:
        """获取滑动窗口状态"""
        rule = self._rules.get(rule_id)
        if not rule:
            return {}
        scope_key = self._build_scope_key(rule, scope_value)
        window = self._windows.get(rule_id, {}).get(scope_key)
        if not window:
            return {}
        return {
            "current_count": window.current_count,
            "max_requests": window.max_requests,
            "window_sec": window.window_sec,
        }

    def reset(self, rule_id: str, scope_value: str = "") -> None:
        """重置限流状态"""
        if scope_value:
            self._buckets.get(rule_id, {}).pop(scope_value, None)
            self._windows.get(rule_id, {}).pop(scope_value, None)
        else:
            self._buckets.pop(rule_id, None)
            self._windows.pop(rule_id, None)


# 预置常见限流规则模板
PRESET_RULES = {
    "api-global": RateLimitRule(
        rule_id="api-global",
        name="Global API Rate Limit",
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        scope=LimitScope.GLOBAL,
        rate=200.0,
        burst=400.0,
    ),
    "api-per-endpoint": RateLimitRule(
        rule_id="api-per-endpoint",
        name="Per-Endpoint Rate Limit",
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
        scope=LimitScope.PER_ENDPOINT,
        window_sec=60,
        max_requests=300,
    ),
    "llm-calls": RateLimitRule(
        rule_id="llm-calls",
        name="LLM Call Rate Limit",
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        scope=LimitScope.GLOBAL,
        rate=50.0,
        burst=100.0,
    ),
    "tenant-api": RateLimitRule(
        rule_id="tenant-api",
        name="Per-Tenant API Rate Limit",
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
        scope=LimitScope.PER_TENANT,
        window_sec=60,
        max_requests=500,
    ),
}
