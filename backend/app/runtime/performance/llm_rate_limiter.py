"""W35-36 Performance Optimization — LLM 自适应限流器

LLMRateLimiter 针对 LLM API 调用的特殊限流需求：
- 429 Too Many Requests 自动检测与节流
- 自适应降速（指数退避式节流）
- 按 Provider/Model 分级控制
- RPM（每分钟请求数）和 TPM（每分钟 Token 数）双重限制
- 自动恢复（在无 429 窗口后逐步恢复全速）

使用方式：
    llm_limiter = LLMRateLimiter()
    llm_limiter.configure(LLMRateLimitConfig(provider="openai", max_rpm=500))

    async with llm_limiter.acquire("openai", "gpt-4", estimated_tokens=1000):
        response = await openai_call(...)

    # 或在收到 429 后通知限流器
    llm_limiter.record_429("openai", "gpt-4")
"""

import asyncio
import time
import math
from typing import Optional, AsyncIterator
from contextlib import asynccontextmanager
from collections import defaultdict

from .models import LLMRateLimitConfig, LLMRateLimitState


class LLMRateLimiter:
    """LLM API 调用自适应限流器

    管理多个 Provider/Model 组合的限流状态。
    检测 429 响应后自动降速，无错误后逐步恢复。
    """

    def __init__(self):
        self._configs: dict[str, LLMRateLimitConfig] = {}  # key = "provider:model"
        self._states: dict[str, LLMRateLimitState] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        # 滑动窗口统计
        self._call_history: dict[str, list[tuple[float, int]]] = defaultdict(list)
        # (timestamp, tokens) tuples for RPM/TPM tracking
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------

    def _make_key(self, provider: str, model: str = "") -> str:
        """构建配置键"""
        return f"{provider}:{model}" if model else f"{provider}:*"

    def configure(self, config: LLMRateLimitConfig) -> None:
        """配置 Provider/Model 限流参数"""
        key = self._make_key(config.provider, config.model)
        self._configs[key] = config

        if key not in self._semaphores:
            self._semaphores[key] = asyncio.Semaphore(config.max_concurrent)

        if key not in self._states:
            self._states[key] = LLMRateLimitState(
                provider=config.provider,
                model=config.model or "*",
            )

    def get_config(self, provider: str, model: str = "") -> Optional[LLMRateLimitConfig]:
        """获取配置（优先精确匹配，回退通配）"""
        exact_key = self._make_key(provider, model)
        wildcard_key = self._make_key(provider, "")
        return self._configs.get(exact_key) or self._configs.get(wildcard_key)

    def _resolve_config(self, provider: str, model: str = "") -> Optional[LLMRateLimitConfig]:
        """解析配置：精确 → 通配 → 默认"""
        cfg = self.get_config(provider, model)
        if cfg:
            return cfg
        # 返回默认配置
        return LLMRateLimitConfig(
            provider=provider,
            model=model,
            max_concurrent=10,
            max_rpm=500,
            max_tpm=1_000_000,
            auto_throttle=True,
        )

    # ------------------------------------------------------------------
    # 核心 API
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def acquire(self, provider: str, model: str = "",
                      estimated_tokens: int = 0) -> AsyncIterator[bool]:
        """获取 LLM 调用许可（上下文管理器）

        用法:
            async with llm_limiter.acquire("openai", "gpt-4", 1000):
                resp = await client.chat.completions.create(...)

        Args:
            provider: LLM Provider 名称
            model: 模型名称
            estimated_tokens: 预估 Token 消耗（用于 TPM 检查）

        Raises:
            RuntimeError: 限流拒绝（非 429，而是主动限流）

        Yields:
            True: 获得许可
        """
        cfg = self._resolve_config(provider, model)
        key = self._make_key(provider, model or cfg.model)
        state_key = key

        # 确保初始化
        if state_key not in self._states:
            self._states[state_key] = LLMRateLimitState(
                provider=provider, model=model or "*"
            )
        if key not in self._semaphores:
            self._semaphores[key] = asyncio.Semaphore(cfg.max_concurrent)

        state = self._states[state_key]

        # 1. 检查 throttle 级别
        if state.is_throttled and state.throttle_level <= 0.0:
            raise RuntimeError(f"LLM calls to {provider}/{model} are fully throttled")

        # 2. 检查 RPM
        if not await self._check_rpm(state_key, cfg):
            raise RuntimeError(f"LLM RPM limit exceeded for {provider}/{model}")

        # 3. 检查 TPM（如果有预估）
        if estimated_tokens > 0:
            if not await self._check_tpm(state_key, cfg, estimated_tokens):
                raise RuntimeError(f"LLM TPM limit exceeded for {provider}/{model}")

        # 4. 获取并发信号量
        # 如果 throttle_level < 1.0，按比例降低实际并发
        adjusted_max = max(1, int(cfg.max_concurrent * state.throttle_level))
        if self._semaphores[key]._value != adjusted_max:
            # 调整信号量（通过重建）
            # 注意：这在并发场景下不够精确，但可接受
            old_sem = self._semaphores[key]
            self._semaphores[key] = asyncio.Semaphore(adjusted_max)

        await self._semaphores[key].acquire()

        try:
            # 记录调用
            async with self._lock:
                state.active_calls += 1
                state.current_rpm += 1
                state.current_tpm += estimated_tokens
                self._call_history[state_key].append((time.monotonic(), estimated_tokens))
                self._prune_call_history(state_key)

            yield True

        finally:
            self._semaphores[key].release()
            async with self._lock:
                state.active_calls -= 1

    def record_429(self, provider: str, model: str = "") -> None:
        """记录一次 429 响应，触发自适应节流"""
        cfg = self._resolve_config(provider, model)
        state_key = self._make_key(provider, model or cfg.model)

        if state_key not in self._states:
            return

        state = self._states[state_key]
        state.consecutive_429 += 1
        state.total_429_count += 1
        state.last_429_time = str(time.time())

        if cfg.auto_throttle:
            # 指数降速：每次 429 将 throttle_level 乘以 factor
            new_level = state.throttle_level * (cfg.throttle_factor ** state.consecutive_429)
            state.throttle_level = new_level
            if new_level < 0.01:
                state.throttle_level = 0.0
                state.is_throttled = True

    def record_success(self, provider: str, model: str = "") -> None:
        """记录一次成功调用，触发逐步恢复"""
        cfg = self._resolve_config(provider, model)
        state_key = self._make_key(provider, model or cfg.model)

        if state_key not in self._states:
            return

        state = self._states[state_key]

        # 有 429 历史：快速恢复（+0.1）
        if state.consecutive_429 > 0:
            recovery = min(1.0, state.throttle_level + 0.1)
            state.throttle_level = recovery
            if recovery >= 1.0:
                state.is_throttled = False
            state.consecutive_429 = 0
        # 仍被节流中：缓慢恢复（+0.1）
        elif state.throttle_level < 1.0:
            recovery = min(1.0, state.throttle_level + 0.1)
            state.throttle_level = recovery
            if recovery >= 1.0:
                state.is_throttled = False

    # ------------------------------------------------------------------
    # RPM / TPM 检查
    # ------------------------------------------------------------------

    async def _check_rpm(self, state_key: str, cfg: LLMRateLimitConfig) -> bool:
        """检查 RPM 限制"""
        self._prune_call_history(state_key)
        rpm = len(self._call_history[state_key])
        effective_rpm = cfg.max_rpm * self._states[state_key].throttle_level
        return rpm < effective_rpm

    async def _check_tpm(self, state_key: str, cfg: LLMRateLimitConfig,
                          estimated_tokens: int) -> bool:
        """检查 TPM 限制"""
        self._prune_call_history(state_key)
        tpm = sum(t for _, t in self._call_history[state_key])
        effective_tpm = cfg.max_tpm * self._states[state_key].throttle_level
        return (tpm + estimated_tokens) <= effective_tpm

    def _prune_call_history(self, state_key: str) -> None:
        """清理超过 60 秒的调用记录"""
        now = time.monotonic()
        cutoff = now - 60.0
        self._call_history[state_key] = [
            (ts, tokens) for ts, tokens in self._call_history[state_key]
            if ts > cutoff
        ]

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def get_state(self, provider: str, model: str = "") -> Optional[LLMRateLimitState]:
        """获取限流状态"""
        state_key = self._make_key(provider, model)
        return self._states.get(state_key)

    def get_all_states(self) -> dict[str, LLMRateLimitState]:
        """获取所有限流状态"""
        return dict(self._states)

    def get_current_rpm(self, provider: str, model: str = "") -> int:
        """获取当前 RPM"""
        state_key = self._make_key(provider, model)
        self._prune_call_history(state_key)
        return len(self._call_history.get(state_key, []))

    def get_current_tpm(self, provider: str, model: str = "") -> int:
        """获取当前 TPM"""
        state_key = self._make_key(provider, model)
        self._prune_call_history(state_key)
        return sum(t for _, t in self._call_history.get(state_key, []))

    def reset(self, provider: str = "", model: str = "") -> None:
        """重置限流状态"""
        if provider:
            state_key = self._make_key(provider, model)
            self._states.pop(state_key, None)
            self._call_history.pop(state_key, None)
            self._semaphores.pop(state_key, None)
        else:
            self._states.clear()
            self._call_history.clear()
            self._semaphores.clear()
