"""
Python Tool Adapter — 在受限沙箱中安全执行 Python 代码
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
import os
from typing import Any, Dict

from app.runtime.tool_runtime.models import ExecutionContext, ExecutionResult, ExecutionStatus

logger = logging.getLogger(__name__)

# 禁止的模块/关键字
FORBIDDEN_IMPORTS = [
    "os.system", "subprocess", "shutil.rmtree", "socket",
    "requests.post", "requests.delete", "requests.put", "requests.patch",
]
FORBIDDEN_KEYWORDS = [
    "__import__", "eval(", "exec(", "compile(", "open(",
    "globals()", "locals()", "getattr(", "setattr(", "delattr(",
]


async def python_execute(
    args: Dict[str, Any],
    context: ExecutionContext,
) -> ExecutionResult:
    """在子进程中安全执行 Python 代码"""
    code = args.get("code", "")
    timeout_sec = args.get("timeout_sec", 10)

    if not code or not code.strip():
        return ExecutionResult(
            tool_name="python_exec",
            status=ExecutionStatus.FAILED,
            error="代码不能为空",
        )

    start = asyncio.get_event_loop().time()

    # 安全检查
    code_lower = code.lower()
    for kw in FORBIDDEN_KEYWORDS:
        if kw in code_lower:
            return ExecutionResult(
                tool_name="python_exec",
                status=ExecutionStatus.DENIED,
                error=f"代码包含禁止的关键字: {kw}",
            )
    for imp in FORBIDDEN_IMPORTS:
        if imp in code_lower:
            return ExecutionResult(
                tool_name="python_exec",
                status=ExecutionStatus.DENIED,
                error=f"代码包含禁止的导入: {imp}",
            )

    # 包装代码以捕获输出
    wrapper = f"""
import sys
import json
from io import StringIO

_stdout = StringIO()
_stderr = StringIO()
sys.stdout = _stdout
sys.stderr = _stderr

_result = None
try:
{chr(10).join('    ' + line for line in code.strip().split(chr(10)))}
    _result = {{"status": "success"}}
except Exception as _e:
    _result = {{"status": "error", "error": str(_e), "type": type(_e).__name__}}

sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__

_output = {{"stdout": _stdout.getvalue(), "stderr": _stderr.getvalue(), "result": _result}}
print(json.dumps(_output))
"""

    try:
        # 写入临时文件
        tmpdir = tempfile.mkdtemp(prefix="py_sandbox_")
        script_path = os.path.join(tmpdir, "_script.py")

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(wrapper)
            f.flush()
            os.fsync(f.fileno())

        python_exe = sys.executable

        proc = await asyncio.create_subprocess_exec(
            python_exe,
            script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tmpdir,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            duration = int((asyncio.get_event_loop().time() - start) * 1000)
            _cleanup(tmpdir)
            return ExecutionResult(
                tool_name="python_exec",
                status=ExecutionStatus.TIMEOUT,
                error=f"代码执行超时 ({timeout_sec}s)",
                duration_ms=duration,
            )

        duration = int((asyncio.get_event_loop().time() - start) * 1000)

        # 清理临时目录
        _cleanup(tmpdir)

        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode == 0 and stdout_str:
            try:
                output_data = json.loads(stdout_str)
                result_data = output_data.get("result", {})
                user_stdout = output_data.get("stdout", "")

                if result_data.get("status") == "error":
                    return ExecutionResult(
                        tool_name="python_exec",
                        status=ExecutionStatus.FAILED,
                        output=user_stdout,
                        error=f"{result_data.get('type', 'Error')}: {result_data.get('error', '')}",
                        duration_ms=duration,
                    )
                else:
                    return ExecutionResult(
                        tool_name="python_exec",
                        status=ExecutionStatus.COMPLETED,
                        output=user_stdout or "(无输出)",
                        duration_ms=duration,
                    )
            except json.JSONDecodeError:
                return ExecutionResult(
                    tool_name="python_exec",
                    status=ExecutionStatus.COMPLETED,
                    output=stdout_str or "(无输出)",
                    duration_ms=duration,
                )
        else:
            return ExecutionResult(
                tool_name="python_exec",
                status=ExecutionStatus.FAILED,
                error=stderr_str or f"Exit code: {proc.returncode}",
                duration_ms=duration,
                exit_code=proc.returncode,
            )

    except Exception as e:
        duration = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionResult(
            tool_name="python_exec",
            status=ExecutionStatus.FAILED,
            error=str(e),
            duration_ms=duration,
        )


def _cleanup(tmpdir: str) -> None:
    """清理临时目录"""
    try:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass
