"""Sandbox — 沙箱管理器（生命周期 + 池化）"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.runtime.sandbox.models import (
    SandboxConfig, SandboxResult, SandboxInfo,
    SandboxType, SandboxStatus, SecurityPolicy, SecurityLevel,
)
from app.runtime.sandbox.security import SecurityValidator
from app.runtime.sandbox.python_sandbox import PythonSandbox


class SandboxManager:
    """沙箱生命周期管理器。
    
    负责创建、复用、销毁沙箱。支持：
    - 按类型创建不同沙箱
    - 沙箱复用（task_id 匹配）
    - 超时自动清理
    - 安全策略注入
    """

    def __init__(self, max_sandboxes: int = 50, idle_timeout_sec: int = 600):
        self._sandboxes: dict[str, PythonSandbox] = {}  # sandbox_id → sandbox
        self._task_sandbox: dict[str, str] = {}          # task_id → sandbox_id
        self._max_sandboxes = max_sandboxes
        self._idle_timeout = idle_timeout_sec
        self._lock = asyncio.Lock()
        self._created_count = 0
        self._destroyed_count = 0

    # ── 创建沙箱 ──

    async def create_sandbox(
        self,
        sandbox_type: SandboxType = SandboxType.PYTHON,
        task_id: str = "",
        security: SecurityPolicy = None,
        **kwargs,
    ) -> PythonSandbox:
        """创建隔离沙箱"""
        async with self._lock:
            # 检查容量
            if len(self._sandboxes) >= self._max_sandboxes:
                await self._evict_idle()

            config = SandboxConfig(
                sandbox_type=sandbox_type,
                task_id=task_id or str(uuid.uuid4())[:8],
                security=security or SecurityPolicy(),
                **kwargs,
            )

            if sandbox_type == SandboxType.PYTHON:
                sandbox = PythonSandbox(config)
            elif sandbox_type == SandboxType.DOCKER:
                # Docker 沙箱：以 Python 沙箱为 fallback
                sandbox = PythonSandbox(config)
            elif sandbox_type == SandboxType.BROWSER:
                sandbox = PythonSandbox(config)
            else:
                # TOOL / SKILL → Python 沙箱
                sandbox = PythonSandbox(config)

            self._sandboxes[sandbox.info.sandbox_id] = sandbox
            if task_id:
                self._task_sandbox[task_id] = sandbox.info.sandbox_id
            self._created_count += 1
            return sandbox

    # ── 获取沙箱 ──

    async def get_sandbox(self, task_id: str) -> Optional[PythonSandbox]:
        """按任务 ID 获取已有沙箱"""
        sandbox_id = self._task_sandbox.get(task_id)
        if sandbox_id:
            sb = self._sandboxes.get(sandbox_id)
            if sb and not sb._is_destroyed:
                return sb
        return None

    async def get_or_create(
        self,
        task_id: str,
        sandbox_type: SandboxType = SandboxType.PYTHON,
        security: SecurityPolicy = None,
    ) -> PythonSandbox:
        """获取已有沙箱或创建新沙箱"""
        existing = await self.get_sandbox(task_id)
        if existing:
            return existing
        return await self.create_sandbox(
            sandbox_type=sandbox_type,
            task_id=task_id,
            security=security,
        )

    # ── 执行代码 ──

    async def execute(
        self,
        code: str,
        task_id: str = "",
        sandbox_type: SandboxType = SandboxType.PYTHON,
        security: SecurityPolicy = None,
    ) -> SandboxResult:
        """在沙箱中执行代码（一站式：获取/创建 + 执行）"""
        sandbox = await self.get_or_create(
            task_id=task_id,
            sandbox_type=sandbox_type,
            security=security,
        )
        return await sandbox.execute(code)

    # ── 销毁沙箱 ──

    async def destroy_sandbox(self, sandbox_id: str) -> bool:
        """销毁指定沙箱（外部调用，带锁）"""
        async with self._lock:
            return await self._destroy_sandbox_unsafe(sandbox_id)

    async def destroy_task_sandbox(self, task_id: str) -> bool:
        """按任务 ID 销毁沙箱（外部调用，带锁）"""
        async with self._lock:
            sandbox_id = self._task_sandbox.pop(task_id, None)
            if sandbox_id:
                return await self._destroy_sandbox_unsafe(sandbox_id)
            return False

    async def destroy_all(self):
        """销毁所有沙箱"""
        async with self._lock:
            ids = list(self._sandboxes.keys())
            for sid in ids:
                await self._destroy_sandbox_unsafe(sid)

    async def _destroy_sandbox_unsafe(self, sandbox_id: str) -> bool:
        """销毁沙箱（内部，调用方必须持有 _lock）"""
        sb = self._sandboxes.pop(sandbox_id, None)
        if sb is None:
            return False
        await sb.cleanup()

        # 清理任务映射
        for tid, sid in list(self._task_sandbox.items()):
            if sid == sandbox_id:
                del self._task_sandbox[tid]

        self._destroyed_count += 1
        return True

    # ── 查询 ──

    def list_sandboxes(self) -> list[SandboxInfo]:
        """列出所有活跃沙箱"""
        return [sb.info for sb in self._sandboxes.values() if not sb._is_destroyed]

    def active_count(self) -> int:
        """活跃沙箱数"""
        return sum(1 for sb in self._sandboxes.values() if not sb._is_destroyed)

    def stats(self) -> dict:
        """统计信息"""
        return {
            "active": self.active_count(),
            "total_created": self._created_count,
            "total_destroyed": self._destroyed_count,
            "max_sandboxes": self._max_sandboxes,
        }

    # ── 内部方法 ──

    async def _evict_idle(self):
        """驱逐空闲沙箱"""
        now = datetime.now(timezone.utc)
        to_remove = []

        for sid, sb in self._sandboxes.items():
            if sb._is_destroyed:
                to_remove.append(sid)
                continue
            try:
                last_used = datetime.fromisoformat(sb.info.last_used_at)
                idle_sec = (now - last_used).total_seconds()
                if idle_sec > self._idle_timeout:
                    to_remove.append(sid)
            except (ValueError, TypeError):
                to_remove.append(sid)

        for sid in to_remove:
            await self._destroy_sandbox_unsafe(sid)
