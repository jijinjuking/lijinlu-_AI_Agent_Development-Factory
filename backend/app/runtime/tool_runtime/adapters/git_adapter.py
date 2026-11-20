"""
Git Tool Adapter — 执行 Git 操作
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

from app.runtime.tool_runtime.models import ExecutionContext, ExecutionResult, ExecutionStatus

logger = logging.getLogger(__name__)


async def git_execute(
    args: Dict[str, Any],
    context: ExecutionContext,
) -> ExecutionResult:
    """执行 Git 操作"""
    operation = args.get("operation", "status")
    repo_url = args.get("repo_url")
    branch = args.get("branch")
    message = args.get("message")
    files = args.get("files", [])
    cwd = args.get("cwd") or os.getcwd()

    start = asyncio.get_event_loop().time()

    # 构建 git 命令
    cmd_parts = ["git"]

    if operation == "clone":
        if not repo_url:
            return ExecutionResult(
                tool_name="git_operation",
                status=ExecutionStatus.FAILED,
                error="clone 操作需要提供 repo_url",
            )
        cmd_parts.extend(["clone", repo_url])
        if branch:
            cmd_parts.extend(["-b", branch])

    elif operation == "pull":
        cmd_parts.append("pull")
        if repo_url:
            cmd_parts.extend([repo_url, branch or ""])

    elif operation == "push":
        cmd_parts.append("push")
        if repo_url:
            cmd_parts.extend([repo_url, branch or ""])

    elif operation == "commit":
        if not message:
            return ExecutionResult(
                tool_name="git_operation",
                status=ExecutionStatus.FAILED,
                error="commit 操作需要提供 message",
            )
        cmd_parts.extend(["commit", "-m", message])
        if files:
            cmd_parts.extend(["--"] + files)
        else:
            cmd_parts.append("-a")

    elif operation == "status":
        cmd_parts.extend(["status", "--porcelain"])

    elif operation == "log":
        cmd_parts.extend(["log", "--oneline", "-20"])
        if branch:
            cmd_parts.append(branch)

    elif operation == "branch":
        cmd_parts.append("branch")
        if branch:
            cmd_parts.append(branch)

    elif operation == "checkout":
        if not branch:
            return ExecutionResult(
                tool_name="git_operation",
                status=ExecutionStatus.FAILED,
                error="checkout 操作需要提供 branch",
            )
        cmd_parts.extend(["checkout", branch])

    elif operation == "diff":
        cmd_parts.append("diff")
        if files:
            cmd_parts.extend(["--"] + files)

    elif operation == "merge":
        if not branch:
            return ExecutionResult(
                tool_name="git_operation",
                status=ExecutionStatus.FAILED,
                error="merge 操作需要提供 branch",
            )
        cmd_parts.extend(["merge", branch])

    else:
        return ExecutionResult(
            tool_name="git_operation",
            status=ExecutionStatus.FAILED,
            error=f"不支持的 Git 操作: {operation}",
        )

    cmd_str = " ".join(cmd_parts)
    logger.info("Git operation: %s [task=%s]", cmd_str, context.task_id)

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd_str,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            duration = int((asyncio.get_event_loop().time() - start) * 1000)
            return ExecutionResult(
                tool_name="git_operation",
                status=ExecutionStatus.TIMEOUT,
                error="Git 操作超时 (60s)",
                duration_ms=duration,
            )

        duration = int((asyncio.get_event_loop().time() - start) * 1000)
        output = stdout.decode("utf-8", errors="replace").strip()
        error_output = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode == 0:
            return ExecutionResult(
                tool_name="git_operation",
                status=ExecutionStatus.COMPLETED,
                output=output or "Git 操作完成",
                exit_code=0,
                duration_ms=duration,
            )
        else:
            # Git 的 stderr 有时是信息性输出
            combined = (output + "\n" + error_output).strip()
            return ExecutionResult(
                tool_name="git_operation",
                status=ExecutionStatus.FAILED,
                output=output,
                error=combined or f"Exit code: {proc.returncode}",
                exit_code=proc.returncode,
                duration_ms=duration,
            )

    except Exception as e:
        duration = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionResult(
            tool_name="git_operation",
            status=ExecutionStatus.FAILED,
            error=str(e),
            duration_ms=duration,
        )
