"""
Shell Tool Adapter — 执行 Shell 命令
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

from app.runtime.tool_runtime.models import ExecutionContext, ExecutionResult, ExecutionStatus

logger = logging.getLogger(__name__)

# 危险命令黑名单
BLOCKED_COMMANDS = [
    "rm -rf /", "dd if=", "mkfs.", ":(){ :|:& };:", "chmod 777 /",
    "> /dev/sda", "format c:", "del /f /s",
]


async def shell_execute(
    args: Dict[str, Any],
    context: ExecutionContext,
) -> ExecutionResult:
    """执行 Shell 命令（通过 subprocess 在受限环境中运行）"""
    command = args.get("command", "")
    cwd = args.get("cwd") or os.getcwd()
    env_vars = args.get("env") or {}

    start = asyncio.get_event_loop().time()

    # 安全检查
    for blocked in BLOCKED_COMMANDS:
        if blocked in command:
            logger.warning("Blocked dangerous command: %s", command[:100])
            return ExecutionResult(
                tool_name="shell_exec",
                status=ExecutionStatus.DENIED,
                error=f"命令包含被禁止的操作: {blocked}",
            )

    try:
        env = os.environ.copy()
        env.update(env_vars)

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            duration = int((asyncio.get_event_loop().time() - start) * 1000)
            return ExecutionResult(
                tool_name="shell_exec",
                status=ExecutionStatus.TIMEOUT,
                error="命令执行超时 (30s)",
                duration_ms=duration,
                exit_code=-1,
            )

        duration = int((asyncio.get_event_loop().time() - start) * 1000)
        output = stdout.decode("utf-8", errors="replace").strip()
        error_output = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode == 0:
            return ExecutionResult(
                tool_name="shell_exec",
                status=ExecutionStatus.COMPLETED,
                output=output or "(无输出)",
                exit_code=0,
                duration_ms=duration,
            )
        else:
            return ExecutionResult(
                tool_name="shell_exec",
                status=ExecutionStatus.FAILED,
                output=output,
                error=error_output or f"Exit code: {proc.returncode}",
                exit_code=proc.returncode,
                duration_ms=duration,
            )

    except FileNotFoundError:
        duration = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionResult(
            tool_name="shell_exec",
            status=ExecutionStatus.FAILED,
            error=f"命令未找到: {command.split()[0] if command else 'N/A'}",
            duration_ms=duration,
            exit_code=127,
        )
    except Exception as e:
        duration = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionResult(
            tool_name="shell_exec",
            status=ExecutionStatus.FAILED,
            error=str(e),
            duration_ms=duration,
            exit_code=-1,
        )
