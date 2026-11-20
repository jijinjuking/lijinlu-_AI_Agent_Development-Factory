"""W35-36 Performance Optimization — 背压控制器

BackpressureController 为 SSE/EventBus/TaskQueue 提供背压保护：
- 队列水位线监控（high/low watermark）
- 4 种背压策略：DROP_OLDEST / DROP_NEWEST / BLOCK / DEGRADE
- 自动激活/解除背压
- 丢弃统计

使用方式：
    bp = BackpressureController(BackpressureConfig(
        target="sse", max_queue_size=1000,
        strategy=BackpressureStrategy.DROP_OLDEST
    ))

    # 入队前检查
    if not bp.can_enqueue():
        bp.handle_overflow(item)  # 按策略处理

    bp.enqueue(item)
"""

import asyncio
import time
from typing import Any, Optional
from collections import deque

from .models import (
    BackpressureConfig, BackpressureStats, BackpressureStrategy
)


class BackpressureController:
    """通用背压控制器

    监控队列水位，在高水位时触发背压策略，
    低水位时解除背压。
    """

    def __init__(self, config: BackpressureConfig):
        self.config = config
        self._queue: deque = deque()
        self._is_active = False
        self._total_dropped = 0
        self._total_degraded = 0
        self._total_blocked = 0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 入队 / 出队
    # ------------------------------------------------------------------

    async def can_enqueue(self) -> bool:
        """检查是否可以入队"""
        if not self.config.enabled:
            return True
        return len(self._queue) < self.config.max_queue_size

    async def enqueue(self, item: Any) -> bool:
        """尝试入队

        Returns:
            True: 成功入队
            False: 背压触发，按策略处理后未入队
        """
        if not self.config.enabled:
            self._queue.append(item)
            return True

        async with self._lock:
            if len(self._queue) < self.config.max_queue_size:
                self._queue.append(item)
                self._check_watermarks()
                return True

            # 队列满，触发背压
            self._is_active = True
            return self._handle_overflow(item)

    async def dequeue(self) -> Optional[Any]:
        """出队"""
        async with self._lock:
            if self._queue:
                item = self._queue.popleft()
                self._check_watermarks()
                return item
            return None

    async def peek(self) -> Optional[Any]:
        """偷看队首但不移除"""
        async with self._lock:
            return self._queue[0] if self._queue else None

    def _handle_overflow(self, item: Any) -> bool:
        """处理队列溢出"""
        strategy = self.config.strategy

        if strategy == BackpressureStrategy.DROP_OLDEST:
            if self._queue:
                self._queue.popleft()
                self._total_dropped += 1
                self._queue.append(item)
                return True  # 替换成功，算入队
            return False

        elif strategy == BackpressureStrategy.DROP_NEWEST:
            self._total_dropped += 1
            return False  # 丢弃新来者

        elif strategy == BackpressureStrategy.BLOCK:
            self._total_blocked += 1
            return False  # 拒绝（调用方应等待重试）

        elif strategy == BackpressureStrategy.DEGRADE:
            self._total_degraded += 1
            return False  # 降级（调用方应返回简化结果）

        return False

    def _check_watermarks(self) -> None:
        """检查水位线"""
        if not self.config.enabled:
            return

        utilization = len(self._queue) / max(1, self.config.max_queue_size)

        if utilization >= self.config.high_watermark:
            self._is_active = True
        elif utilization <= self.config.low_watermark:
            self._is_active = False

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(self) -> BackpressureStats:
        """获取背压统计"""
        utilization = len(self._queue) / max(1, self.config.max_queue_size)
        return BackpressureStats(
            target=self.config.target,
            queue_size=len(self._queue),
            max_size=self.config.max_queue_size,
            utilization=round(utilization, 4),
            is_active=self._is_active,
            total_dropped=self._total_dropped,
            total_degraded=self._total_degraded,
            total_blocked=self._total_blocked,
            strategy=self.config.strategy.value,
        )

    def reset_stats(self) -> None:
        """重置统计"""
        self._total_dropped = 0
        self._total_degraded = 0
        self._total_blocked = 0

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def utilization(self) -> float:
        return len(self._queue) / max(1, self.config.max_queue_size)

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------

    def update_config(self, **kwargs) -> None:
        """更新配置"""
        for k, v in kwargs.items():
            if hasattr(self.config, k):
                setattr(self.config, k, v)

    def clear_queue(self) -> int:
        """清空队列，返回清空的数量"""
        count = len(self._queue)
        self._queue.clear()
        self._is_active = False
        return count


class BackpressureManager:
    """背压管理器

    管理多个 BackpressureController 实例（SSE/EventBus/TaskQueue）。
    """

    def __init__(self):
        self._controllers: dict[str, BackpressureController] = {}

    def register(self, config: BackpressureConfig) -> BackpressureController:
        """注册背压控制器"""
        controller = BackpressureController(config)
        self._controllers[config.target] = controller
        return controller

    def get(self, target: str) -> Optional[BackpressureController]:
        """获取控制器"""
        return self._controllers.get(target)

    def list_targets(self) -> list[str]:
        """列出所有背压目标"""
        return list(self._controllers.keys())

    def get_all_stats(self) -> list[BackpressureStats]:
        """获取所有背压统计"""
        return [ctrl.get_stats() for ctrl in self._controllers.values()]

    def unregister(self, target: str) -> bool:
        """注销控制器"""
        if target in self._controllers:
            del self._controllers[target]
            return True
        return False
