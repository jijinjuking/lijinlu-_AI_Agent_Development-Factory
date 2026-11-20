"""
Docker Sandbox — Docker 容器隔离执行

使用 Docker 容器实现完全隔离的代码执行环境。
需要 Docker daemon 运行。不可用时降级为 PythonSandbox。
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
import os
import time
from typing import Any

from app.runtime.sandbox.models import (
    SandboxConfig, SandboxResult, SandboxStatus, SandboxType, SecurityLevel,
)
from app.runtime.sandbox.security import SecurityValidator

logger = logging.getLogger(__name__)


class DockerSandbox:
    """Docker 容器沙箱。

    功能：
    - Docker 容器创建/执行/销毁
    - 资源限制（CPU/内存/磁盘）
    - 网络隔离
    - 卷挂载（只读/读写）
    - Docker 不可用时自动降级为 PythonSandbox
    """

    DOCKER_IMAGE = "python:3.11-slim"
    DEFAULT_TIMEOUT = 30

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig(sandbox_type=SandboxType.DOCKER)
        self._validator = SecurityValidator(config.security_policy if config else None)
        self._docker_available: bool | None = None

    async def _check_docker(self) -> bool:
        """检测 Docker 是否可用"""
        if self._docker_available is not None:
            return self._docker_available
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "version", "--format", "{{.Server.Version}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            self._docker_available = proc.returncode == 0
            if self._docker_available:
                logger.info("Docker available: version=%s", stdout.decode().strip())
            else:
                logger.warning("Docker not available, will use PythonSandbox fallback")
        except Exception as e:
            logger.warning("Docker check failed: %s", e)
            self._docker_available = False
        return self._docker_available

    async def execute(self, code: str, context: dict = None, timeout: int = None) -> SandboxResult:
        """在 Docker 容器中执行代码"""
        if not await self._check_docker():
            return await self._fallback_python(code, context, timeout)

        # 安全检查
        if self.config.security_level not in (SecurityLevel.NONE,):
            is_safe, message = self._validator.validate_code(code)
            if not is_safe:
                return SandboxResult(
                    success=False, output="", error=f"Security violation: {message}",
                    exit_code=1, duration_ms=0,
                )

        timeout = timeout or self.config.timeout_seconds or self.DEFAULT_TIMEOUT

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8",
        ) as f:
            f.write(code)
            script_path = f.name

        try:
            cmd = [
                "docker", "run", "--rm",
                "--network", "none" if self.config.network_disabled else "bridge",
                f"--memory={self.config.memory_limit_mb}m",
                f"--cpus={self.config.cpu_limit}",
                f"--read-only" if self.config.readonly_fs else "",
                "-v", f"{script_path}:/code/script.py:ro",
                "-w", "/code",
                self.DOCKER_IMAGE,
                "python", "script.py",
            ]
            # 过滤空字符串
            cmd = [c for c in cmd if c]

            start = time.monotonic()
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return SandboxResult(
                    success=False, output="", error=f"Execution timed out after {timeout}s",
                    exit_code=-1, duration_ms=int((time.monotonic() - start) * 1000),
                )

            duration_ms = int((time.monotonic() - start) * 1000)
            output = stdout.decode("utf-8", errors="replace")
            error = stderr.decode("utf-8", errors="replace")

            return SandboxResult(
                success=proc.returncode == 0,
                output=output,
                error=error if proc.returncode != 0 else "",
                exit_code=proc.returncode,
                duration_ms=duration_ms,
                metadata={"sandbox_type": "docker"},
            )

        except FileNotFoundError:
            logger.warning("docker command not found, using fallback")
            return await self._fallback_python(code, context, timeout)
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    async def _fallback_python(self, code: str, context: dict = None, timeout: int = None) -> SandboxResult:
        """Docker 不可用时降级为 PythonSandbox"""
        from app.runtime.sandbox.python_sandbox import PythonSandbox
        logger.info("DockerSandbox falling back to PythonSandbox")
        sandbox = PythonSandbox(self.config)
        result = await sandbox.execute(code, context, timeout)
        if result.metadata is None:
            result.metadata = {}
        result.metadata["sandbox_type"] = "python_fallback"
        return result

    async def cleanup(self) -> None:
        """清理 Docker 资源（悬空容器）"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "container", "prune", "-f",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception:
            pass
