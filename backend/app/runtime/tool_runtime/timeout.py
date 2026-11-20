"""
Timeout Handler — 超时控制
基于 asyncio.wait_for 的超时封装
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, TypeVar

from app.runtime.tool_runtime.models import ExecutionResult, ExecutionStatus

logger = logging.getLogger(__name__)
T = TypeVar("T")


class TimeoutHandler:
    """
    超时处理器 — 封装超时逻辑并返回标准化错误
    """

    async def execute_with_timeout(
        self,
        coro: Coroutine[Any, Any, T],
        timeout_sec: int,
        tool_name: str = "unknown",
        on_timeout: Callable[[], Any] | None = None,
    ) -> T | ExecutionResult:
        """
        在超时限制下执行协程
        超时时返回 ExecutionResult(timeout)，否则返回原始结果
        """
        try:
            return await asyncio.wait_for(coro, timeout=timeout_sec)
        except asyncio.TimeoutError:
            if on_timeout:
                try:
                    on_timeout()
                except Exception:
                    pass
            logger.warning("Tool '%s' timed out after %ds", tool_name, timeout_sec)
            return ExecutionResult(
                tool_name=tool_name,
                status=ExecutionStatus.TIMEOUT,
                error=f"执行超时 ({timeout_sec}s)",
                duration_ms=timeout_sec * 1000,
            )
