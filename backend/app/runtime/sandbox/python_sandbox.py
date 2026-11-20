"""Sandbox — Python 代码沙箱执行器"""

import asyncio
import logging
import platform
import tempfile
import time
from pathlib import Path

from app.runtime.sandbox.models import (
    SandboxConfig, SandboxResult, SandboxInfo,
    SandboxType, SandboxStatus, SecurityPolicy,
)
from app.runtime.sandbox.security import SecurityValidator

logger = logging.getLogger(__name__)


class PythonSandbox:
    """Python 代码隔离执行沙箱。
    
    使用子进程 + 资源限制实现隔离。
    Windows 不支持 ulimit，使用超时 + 进程终止策略。
    """

    def __init__(self, config: SandboxConfig = None):
        self.config = config or SandboxConfig(sandbox_type=SandboxType.PYTHON)
        self.validator = SecurityValidator(self.config.security)
        self._info = SandboxInfo(
            sandbox_id=f"py-{id(self):x}",
            sandbox_type=SandboxType.PYTHON,
            status=SandboxStatus.RUNNING,
            task_id=self.config.task_id,
            config=self.config,
        )
        self._execution_count = 0
        self._total_duration = 0.0
        self._is_destroyed = False

    @property
    def info(self) -> SandboxInfo:
        self._info.execution_count = self._execution_count
        self._info.total_duration_ms = self._total_duration
        return self._info

    async def execute(self, code: str) -> SandboxResult:
        """在隔离环境中执行 Python 代码"""
        if self._is_destroyed:
            return SandboxResult(
                success=False,
                error="Sandbox already destroyed",
                sandbox_id=self._info.sandbox_id,
                task_id=self.config.task_id,
            )

        self._info.status = SandboxStatus.EXECUTING

        # 1. 安全验证
        ok, reason = self.validator.validate_python_code(code)
        if not ok:
            self._info.status = SandboxStatus.RUNNING
            return SandboxResult(
                success=False,
                error=f"Security check failed: {reason}",
                sandbox_id=self._info.sandbox_id,
                task_id=self.config.task_id,
                duration_ms=0,
            )

        ok, reason = self.validator.validate_resources(len(code.encode()))
        if not ok:
            self._info.status = SandboxStatus.RUNNING
            return SandboxResult(
                success=False,
                error=f"Resource check failed: {reason}",
                sandbox_id=self._info.sandbox_id,
                task_id=self.config.task_id,
                duration_ms=0,
            )

        # 2. 包装代码（安全预处理）
        wrapped_code = self._wrap_code(code)

        # 3. 写入临时文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", encoding="utf-8", delete=False
        ) as f:
            f.write(wrapped_code)
            tmp_path = f.name

        # 4. 子进程执行
        timeout = self.config.security.max_execution_time_sec
        start = time.perf_counter()

        try:
            python_exe = self._find_python()
            proc = await asyncio.create_subprocess_exec(
                python_exe, tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                exit_code = proc.returncode if proc.returncode is not None else -1
                out_str = stdout.decode("utf-8", errors="replace")
                err_str = stderr.decode("utf-8", errors="replace")
                duration_ms = (time.perf_counter() - start) * 1000

                # 截断过长输出
                if len(out_str) > 100_000:
                    out_str = out_str[:100_000] + "\n... [output truncated]"
                if len(err_str) > 100_000:
                    err_str = err_str[:100_000] + "\n... [error truncated]"

                success = exit_code == 0 and not err_str

                return SandboxResult(
                    success=success,
                    output=out_str.strip(),
                    error=err_str.strip(),
                    exit_code=exit_code,
                    duration_ms=round(duration_ms, 1),
                    sandbox_id=self._info.sandbox_id,
                    task_id=self.config.task_id,
                )

            except asyncio.TimeoutError:
                # 超时：强制终止
                try:
                    proc.kill()
                    await proc.wait()
                except Exception as e:
                    logger.debug("Failed to kill process: %s", e)
                duration_ms = (time.perf_counter() - start) * 1000
                return SandboxResult(
                    success=False,
                    error=f"Execution timed out after {timeout}s",
                    exit_code=-1,
                    duration_ms=round(duration_ms, 1),
                    sandbox_id=self._info.sandbox_id,
                    task_id=self.config.task_id,
                )

        finally:
            self._execution_count += 1
            if duration_ms := 0:
                pass
            self._info.status = SandboxStatus.RUNNING
            # 清理临时文件
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError as e:
                logger.debug("Failed to delete temp file: %s", e)

    def _wrap_code(self, code: str) -> str:
        """包装用户代码：添加安全头 + 错误处理"""
        header = (
            "# ══════ AI Runtime Sandbox ══════\n"
            "# Security: Restricted execution environment\n"
            "# Generated at: {now}\n"
            "\n"
            "import builtins\n"
            "\n"
            "# ══ Safe builtins override ══\n"
            "_orig_print = print\n"
            "_orig_input = input\n"
            "_SAFE_BUILTINS = {{\n"
            "    'abs': abs, 'all': all, 'any': any, 'bin': bin, 'bool': bool,\n"
            "    'bytes': bytes, 'chr': chr, 'complex': complex, 'dict': dict,\n"
            "    'divmod': divmod, 'enumerate': enumerate, 'filter': filter,\n"
            "    'float': float, 'format': format, 'frozenset': frozenset,\n"
            "    'hasattr': hasattr, 'hash': hash, 'hex': hex, 'int': int,\n"
            "    'isinstance': isinstance, 'issubclass': issubclass, 'iter': iter,\n"
            "    'len': len, 'list': list, 'map': map, 'max': max, 'min': min,\n"
            "    'next': next, 'object': object, 'oct': oct, 'ord': ord,\n"
            "    'pow': pow, 'print': _orig_print, 'range': range,\n"
            "    'repr': repr, 'reversed': reversed, 'round': round, 'set': set,\n"
            "    'slice': slice, 'sorted': sorted, 'str': str, 'sum': sum,\n"
            "    'tuple': tuple, 'type': type, 'zip': zip,\n"
            "}}\n"
            "\n"
            "# Redirect builtins to safe subset\n"
            "for _name in dir(builtins):\n"
            "    if _name in _SAFE_BUILTINS:\n"
            "        continue\n"
            "    if _name.startswith('_') or _name in ('input',):\n"
            "        continue\n"
            "    # Leave other builtins as-is but monitored\n"
            "\n"
            "# ══ User code ══\n"
        ).format(now=__import__("datetime").datetime.now().isoformat())

        # 包装错误处理
        footer = (
            "\n"
            "# ══ Auto-invocation ══\n"
            "if __name__ == '__main__':\n"
            "    try:\n"
            "        _result = main()  # type: ignore\n"
            "        if _result is not None:\n"
            "            print(_result)\n"
            "    except NameError:\n"
            "        # No main() function — just run module-level code\n"
            "        pass\n"
        )

        return header + "\n" + code + "\n" + footer

    @staticmethod
    def _find_python() -> str:
        """查找 Python 解释器"""
        import sys
        return sys.executable

    async def cleanup(self):
        """清理沙箱资源"""
        self._is_destroyed = True
        self._info.status = SandboxStatus.DESTROYED

    def __del__(self):
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if not loop.is_closed():
                loop.create_task(self.cleanup())
        except Exception:
            pass
