"""W35-36 Performance Optimization — 全局并发控制器

ConcurrencyController 提供运行时的全局并发控制能力：
- asyncio.Semaphore 限制活跃任务数（目标 100 并发）
- 等待队列管理（FIFO，含超时）
- 自适应模式：根据 CPU 负载动态扩缩容
- 统计信息收集

使用方式：
    cc = ConcurrencyController(ConcurrencyConfig(max_concurrent=100))
    async with cc.acquire() as ticket:
        await do_work(...)
"""

import asyncio
import time
from typing import Optional, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from .models import (
    ConcurrencyConfig, ConcurrencyStats, ConcurrencyMode
)


@dataclass
class _Ticket:
    """并发入场券"""
    ticket_id: int = 0
    acquired_at: float = 0.0
    task_id: str = ""


class ConcurrencyController:
    """全局并发控制器

    控制同时执行的任务数量，支持固定上限和自适应模式。
    内建等待队列和超时机制。
    """

    def __init__(self, config: Optional[ConcurrencyConfig] = None):
        self.config = config or ConcurrencyConfig()
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._initialized = False

        # 统计
        self._total_admitted: int = 0
        self._total_rejected: int = 0
        self._total_completed: int = 0
        self._total_timed_out: int = 0
        self._peak_concurrent: int = 0
        self._wait_times: list[float] = []
        self._active_count: int = 0
        self._ticket_seq: int = 0
        self._last_scale_time: float = 0.0

        # 自适应状态
        self._current_max: int = self.config.max_concurrent

        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """初始化并发控制器"""
        self._semaphore = asyncio.Semaphore(self._current_max)
        self._last_scale_time = time.monotonic()
        self._initialized = True

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    # ------------------------------------------------------------------
    # 核心 API
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def acquire(self, task_id: str = "",
                      timeout_sec: Optional[float] = None) -> AsyncIterator[_Ticket]:
        """获取并发执行许可

        用法:
            async with cc.acquire("task-123") as ticket:
                await process()

        Args:
            task_id: 任务标识（用于统计）
            timeout_sec: 等待超时秒数，None 使用配置默认值

        Raises:
            asyncio.TimeoutError: 超时未能获取
        """
        await self._ensure_initialized()

        timeout = timeout_sec if timeout_sec is not None else self.config.queue_timeout_sec
        start = time.monotonic()

        try:
            acquired = await asyncio.wait_for(
                self._semaphore.acquire(), timeout=timeout
            )
            wait_time = time.monotonic() - start
        except asyncio.TimeoutError:
            async with self._lock:
                self._total_timed_out += 1
                self._total_rejected += 1
            raise

        self._ticket_seq += 1
        ticket = _Ticket(
            ticket_id=self._ticket_seq,
            acquired_at=time.monotonic(),
            task_id=task_id,
        )

        async with self._lock:
            self._active_count += 1
            self._total_admitted += 1
            if self._active_count > self._peak_concurrent:
                self._peak_concurrent = self._active_count
            self._wait_times.append(wait_time)

        try:
            yield ticket
        finally:
            self._semaphore.release()
            async with self._lock:
                self._active_count -= 1
                self._total_completed += 1

    async def try_acquire(self) -> Optional[_Ticket]:
        """非阻塞尝试获取许可，失败返回 None"""
        await self._ensure_initialized()

        # asyncio.Semaphore 不支持 try_acquire
        # 先检查 _value：>0 表示有可用槽位
        if not self._semaphore or self._semaphore._value <= 0:
            return None

        # 有槽位，直接 acquire（此时应为瞬时完成）
        await self._semaphore.acquire()

        self._ticket_seq += 1
        ticket = _Ticket(ticket_id=self._ticket_seq, acquired_at=time.monotonic())
        async with self._lock:
            self._active_count += 1
            self._total_admitted += 1
            if self._active_count > self._peak_concurrent:
                self._peak_concurrent = self._active_count
        return ticket

    def release(self, ticket: _Ticket) -> None:
        """手动释放许可（如果未使用 async with）"""
        self._semaphore.release()

    # ------------------------------------------------------------------
    # 自适应扩缩容
    # ------------------------------------------------------------------

    async def adaptive_check(self, cpu_percent: float) -> None:
        """自适应检查：根据 CPU 负载动态调整并发上限

        应在周期性循环中调用。
        """
        if self.config.mode != ConcurrencyMode.ADAPTIVE:
            return

        now = time.monotonic()
        if now - self._last_scale_time < self.config.cooldown_sec:
            return

        async with self._lock:
            old_max = self._current_max
            if cpu_percent > self.config.cpu_high_threshold:
                # 负载过高 → 缩容
                new_max = max(
                    self.config.min_concurrent,
                    self._current_max - self.config.scale_down_step
                )
            elif cpu_percent < self.config.cpu_low_threshold:
                # 负载较低 → 扩容
                new_max = min(
                    self.config.max_concurrent,
                    self._current_max + self.config.scale_up_step
                )
            else:
                return

            if new_max != old_max:
                await self._resize_semaphore(new_max)
                self._current_max = new_max
                self._last_scale_time = now

    async def _resize_semaphore(self, new_max: int) -> None:
        """调整 Semaphore 大小（通过重建实现）"""
        # 创建新的 Semaphore 并迁移当前计数
        current_held = self.config.max_concurrent - self._semaphore._value
        new_value = new_max - current_held
        self._semaphore = asyncio.Semaphore(max(1, new_value))

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(self) -> ConcurrencyStats:
        """获取并发控制统计"""
        wait_avg = 0.0
        if self._wait_times:
            wait_avg = sum(self._wait_times[-100:]) / min(len(self._wait_times), 100)

        queue_length = 0
        if self._semaphore:
            # Semaphore._value 是剩余许可数
            held = self._current_max - self._semaphore._value
            queue_length = max(0, held - self._active_count)

        return ConcurrencyStats(
            max_allowed=self._current_max,
            current_active=self._active_count,
            queue_length=queue_length,
            total_admitted=self._total_admitted,
            total_rejected=self._total_rejected,
            total_completed=self._total_completed,
            total_timed_out=self._total_timed_out,
            avg_wait_time_sec=round(wait_avg, 4),
            peak_concurrent=self._peak_concurrent,
            mode=self.config.mode.value,
        )

    def reset_stats(self) -> None:
        """重置统计计数器"""
        self._total_admitted = 0
        self._total_rejected = 0
        self._total_completed = 0
        self._total_timed_out = 0
        self._peak_concurrent = 0
        self._wait_times.clear()

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------

    def update_config(self, config: ConcurrencyConfig) -> None:
        """更新配置"""
        self.config = config
        self._current_max = config.max_concurrent
        # 注意：semaphore 重建在下一次 initialize() 或 adaptive_check() 时完成

    @property
    def is_available(self) -> bool:
        """是否有可用槽位"""
        if not self._semaphore:
            return True
        return not self._semaphore.locked()

    @property
    def available_slots(self) -> int:
        """当前可用槽位数"""
        if not self._semaphore:
            return self._current_max
        return self._semaphore._value
