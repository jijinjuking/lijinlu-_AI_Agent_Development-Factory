"""W12 Sandbox System — 测试套件"""

import pytest
import asyncio
import time

from app.runtime.sandbox import (
    SandboxManager,
    PythonSandbox,
    SecurityValidator,
    SecurityPolicy,
    SecurityLevel,
    SandboxConfig,
    SandboxType,
    SandboxStatus,
    SandboxResult,
    SandboxInfo,
)


# ═══════════════════════════════════════════════════════════════
# SecurityPolicy
# ═══════════════════════════════════════════════════════════════

class TestSecurityPolicy:
    """安全策略配置测试"""

    def test_default_policy_medium(self):
        policy = SecurityPolicy()
        assert policy.level == SecurityLevel.MEDIUM
        assert policy.allow_network is True
        assert policy.max_memory_mb == 512
        assert policy.max_execution_time_sec == 300

    def test_custom_policy(self):
        policy = SecurityPolicy(
            level=SecurityLevel.HIGH,
            allow_network=False,
            max_memory_mb=256,
            max_execution_time_sec=60,
        )
        assert policy.level == SecurityLevel.HIGH
        assert policy.allow_network is False
        assert policy.max_memory_mb == 256

    def test_policy_allowed_commands(self):
        policy = SecurityPolicy()
        assert "python" in policy.allowed_commands
        assert "git" in policy.allowed_commands

    def test_policy_blocked_commands(self):
        policy = SecurityPolicy()
        assert any("rm" in c for c in policy.blocked_commands)

    def test_policy_blocked_modules(self):
        policy = SecurityPolicy()
        assert "os" in policy.python_blocked_modules
        assert "subprocess" in policy.python_blocked_modules
        assert "shutil" in policy.python_blocked_modules

    def test_security_levels(self):
        levels = list(SecurityLevel)
        assert len(levels) == 4
        assert SecurityLevel.NONE in levels
        assert SecurityLevel.HIGH in levels


# ═══════════════════════════════════════════════════════════════
# SecurityValidator
# ═══════════════════════════════════════════════════════════════

class TestSecurityValidator:
    """安全验证器测试"""

    @pytest.fixture
    def strict_validator(self):
        return SecurityValidator(SecurityPolicy(level=SecurityLevel.HIGH))

    @pytest.fixture
    def lenient_validator(self):
        return SecurityValidator(SecurityPolicy(level=SecurityLevel.LOW))

    @pytest.fixture
    def default_validator(self):
        return SecurityValidator()

    # ── 命令验证 ──

    def test_allow_whitelisted_command(self, default_validator):
        ok, reason = default_validator.validate_command("python script.py")
        assert ok
        assert reason == "OK"

    def test_block_unknown_command(self, default_validator):
        ok, reason = default_validator.validate_command("sudo rm -rf /tmp")
        assert not ok
        assert ("not allowed" in reason or "Blocked" in reason)

    def test_block_blocked_pattern(self, default_validator):
        ok, reason = default_validator.validate_command("rm -rf /some/path")
        assert not ok

    def test_block_network_command_high(self, strict_validator):
        ok, reason = strict_validator.validate_command("curl https://example.com")
        assert not ok
        assert "Network" in reason

    def test_allow_git_command(self, default_validator):
        ok, _ = default_validator.validate_command("git clone repo")
        assert ok

    def test_allow_pip_command(self, default_validator):
        ok, _ = default_validator.validate_command("pip install requests")
        assert ok

    # ── 网络验证 ──

    def test_allow_normal_host(self, default_validator):
        ok, _ = default_validator.validate_network("api.github.com")
        assert ok

    def test_block_metadata_host(self, default_validator):
        ok, reason = default_validator.validate_network("169.254.169.254")
        assert not ok
        assert "Blocked" in reason

    def test_block_network_disabled(self):
        policy = SecurityPolicy(allow_network=False)
        validator = SecurityValidator(policy)
        ok, reason = validator.validate_network("google.com")
        assert not ok
        assert "disabled" in reason

    def test_allowlist_network(self):
        policy = SecurityPolicy(allowed_hosts=["api.github.com", "pypi.org"])
        validator = SecurityValidator(policy)
        ok, _ = validator.validate_network("api.github.com")
        assert ok
        ok2, _ = validator.validate_network("google.com")
        assert not ok2

    # ── 路径验证 ──

    def test_allow_normal_path(self, default_validator):
        ok, _ = default_validator.validate_path("/tmp/workspace")
        assert ok

    def test_block_sensitive_path(self, default_validator):
        ok, reason = default_validator.validate_path("/etc/passwd")
        assert not ok
        assert "Blocked" in reason

    def test_block_ssh_path(self, default_validator):
        ok, reason = default_validator.validate_path("/root/.ssh/id_rsa")
        assert not ok

    def test_block_write_readonly(self):
        policy = SecurityPolicy(read_only=True)
        validator = SecurityValidator(policy)
        ok, reason = validator.validate_path("/tmp/file.txt", write=True)
        assert not ok
        assert "read-only" in reason

    def test_allowlist_path(self):
        policy = SecurityPolicy(allowed_paths=["/workspace"])
        validator = SecurityValidator(policy)
        ok, _ = validator.validate_path("/workspace/script.py")
        assert ok
        ok2, _ = validator.validate_path("/tmp/other.py")
        assert not ok2

    # ── Python 导入验证 ──

    def test_block_os_import(self, default_validator):
        ok, reason = default_validator.validate_import("os")
        assert not ok

    def test_block_subprocess_import(self, default_validator):
        ok, _ = default_validator.validate_import("subprocess")
        assert not ok

    def test_allow_safe_import(self, default_validator):
        ok, _ = default_validator.validate_import("json")
        assert ok
        ok, _ = default_validator.validate_import("math")
        assert ok
        ok, _ = default_validator.validate_import("datetime")
        assert ok

    def test_allowlist_imports(self):
        policy = SecurityPolicy(python_allow_imports=["math", "json", "requests"])
        validator = SecurityValidator(policy)
        ok, _ = validator.validate_import("math")
        assert ok
        ok2, _ = validator.validate_import("os")
        assert not ok2  # os is always blocked
        ok3, _ = validator.validate_import("datetime")
        assert not ok3  # not in allowlist

    # ── Python 代码静态检查 ──

    def test_allow_safe_code(self, default_validator):
        ok, _ = default_validator.validate_python_code("x = 1 + 2\nprint(x)")
        assert ok

    def test_block_os_import_in_code(self, default_validator):
        ok, reason = default_validator.validate_python_code("import os\nos.system('ls')")
        assert not ok
        assert "os" in reason

    def test_block_eval(self, default_validator):
        ok, reason = default_validator.validate_python_code("eval('1+1')")
        assert not ok
        assert "eval" in reason.lower()

    def test_block_exec(self, default_validator):
        ok, reason = default_validator.validate_python_code("exec('print(1)')")
        assert not ok

    def test_block_subprocess_in_code(self, default_validator):
        ok, reason = default_validator.validate_python_code(
            "import subprocess\nsubprocess.run(['ls'])"
        )
        assert not ok

    def test_block_from_os_import(self, default_validator):
        ok, _ = default_validator.validate_python_code("from os import system")
        assert not ok

    def test_block_absolute_path_open(self, default_validator):
        ok, _ = default_validator.validate_python_code("open('/etc/passwd')")
        assert not ok

    def test_lenient_allows_dangerous(self, lenient_validator):
        """LOW 安全级别允许危险操作"""
        ok, _ = lenient_validator.validate_python_code("import os")
        assert ok
        ok, _ = lenient_validator.validate_python_code("eval('1+1')")
        assert ok

    # ── 资源检查 ──

    def test_code_size_ok(self, default_validator):
        ok, _ = default_validator.validate_resources(1000)
        assert ok

    def test_code_size_too_large(self):
        policy = SecurityPolicy(max_memory_mb=1)
        validator = SecurityValidator(policy)
        ok, reason = validator.validate_resources(2 * 1024 * 1024)  # 2MB
        assert not ok
        assert "exceeds" in reason


# ═══════════════════════════════════════════════════════════════
# PythonSandbox
# ═══════════════════════════════════════════════════════════════

class TestPythonSandbox:
    """Python 代码执行沙箱测试"""

    @pytest.fixture
    def sandbox(self):
        config = SandboxConfig(
            sandbox_type=SandboxType.PYTHON,
            task_id="test-001",
            security=SecurityPolicy(level=SecurityLevel.LOW),
        )
        return PythonSandbox(config)

    @pytest.fixture
    def strict_sandbox(self):
        config = SandboxConfig(
            sandbox_type=SandboxType.PYTHON,
            task_id="test-strict",
        )
        return PythonSandbox(config)

    @pytest.mark.asyncio
    async def test_execute_simple(self, sandbox):
        result = await sandbox.execute("print('hello world')")
        assert result.success
        assert "hello world" in result.output

    @pytest.mark.asyncio
    async def test_execute_with_main(self, sandbox):
        code = "def main():\n    return 42"
        result = await sandbox.execute(code)
        assert result.success
        assert "42" in result.output

    @pytest.mark.asyncio
    async def test_execute_math(self, sandbox):
        code = "def main():\n    return sum(range(100))"
        result = await sandbox.execute(code)
        assert result.success
        assert "4950" in result.output

    @pytest.mark.asyncio
    async def test_execute_list_comp(self, sandbox):
        code = "def main():\n    return [x**2 for x in range(10)]"
        result = await sandbox.execute(code)
        assert result.success
        assert "0, 1, 4" in result.output

    @pytest.mark.asyncio
    async def test_execute_dict(self, sandbox):
        code = (
            "def main():\n"
            "    d = {'a': 1, 'b': 2}\n"
            "    return sorted(d.items())"
        )
        result = await sandbox.execute(code)
        assert result.success
        assert "a" in result.output

    @pytest.mark.asyncio
    async def test_execute_with_error(self, sandbox):
        code = "def main():\n    return 1 / 0"
        result = await sandbox.execute(code)
        assert not result.success
        assert "ZeroDivisionError" in result.error

    @pytest.mark.asyncio
    async def test_execute_syntax_error(self, sandbox):
        code = "def main()\n    return 1"  # 缺少冒号
        result = await sandbox.execute(code)
        assert not result.success

    @pytest.mark.asyncio
    async def test_block_dangerous_code(self, strict_sandbox):
        code = "import os\nos.system('echo hacked')"
        result = await strict_sandbox.execute(code)
        assert not result.success
        assert "Security" in result.error

    @pytest.mark.asyncio
    async def test_sandbox_info(self, sandbox):
        info = sandbox.info
        assert info.sandbox_type == SandboxType.PYTHON
        assert info.task_id == "test-001"
        assert info.execution_count == 0

    @pytest.mark.asyncio
    async def test_execution_updates_info(self, sandbox):
        await sandbox.execute("print('test')")
        assert sandbox.info.execution_count == 1

    @pytest.mark.asyncio
    async def test_destroyed_sandbox(self, sandbox):
        await sandbox.cleanup()
        result = await sandbox.execute("print('test')")
        assert not result.success
        assert "destroyed" in result.error

    @pytest.mark.asyncio
    async def test_result_has_duration(self, sandbox):
        result = await sandbox.execute("print('test')")
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_result_has_sandbox_id(self, sandbox):
        result = await sandbox.execute("print('test')")
        assert result.sandbox_id
        assert result.task_id == "test-001"

    @pytest.mark.asyncio
    async def test_large_output(self, sandbox):
        code = f"def main():\n    return 'x' * 110000"
        result = await sandbox.execute(code)
        assert len(result.output) <= 100_000 + 50  # 截断

    @pytest.mark.asyncio
    async def test_timeout_small(self, sandbox):
        # 使用极短超时
        sandbox.config.security.max_execution_time_sec = 0.5
        code = "def main():\n    import time; time.sleep(10)"
        result = await sandbox.execute(code)
        assert not result.success
        assert "timed out" in result.error.lower()


# ═══════════════════════════════════════════════════════════════
# SandboxManager
# ═══════════════════════════════════════════════════════════════

class TestSandboxManager:
    """沙箱管理器测试"""

    @staticmethod
    async def _make_manager() -> SandboxManager:
        return SandboxManager(max_sandboxes=10, idle_timeout_sec=999)

    @pytest.mark.asyncio
    async def test_create_sandbox(self):
        mgr = await self._make_manager()
        try:
            sb = await mgr.create_sandbox(task_id="task-1")
            assert sb is not None
            assert mgr.active_count() == 1
        finally:
            await mgr.destroy_all()

    @pytest.mark.asyncio
    async def test_get_sandbox(self):
        mgr = await self._make_manager()
        try:
            await mgr.create_sandbox(task_id="task-1")
            sb = await mgr.get_sandbox("task-1")
            assert sb is not None
        finally:
            await mgr.destroy_all()

    @pytest.mark.asyncio
    async def test_get_nonexistent(self):
        mgr = await self._make_manager()
        try:
            sb = await mgr.get_sandbox("nonexistent")
            assert sb is None
        finally:
            await mgr.destroy_all()

    @pytest.mark.asyncio
    async def test_get_or_create_existing(self):
        mgr = await self._make_manager()
        try:
            sb1 = await mgr.get_or_create("task-1")
            sb2 = await mgr.get_or_create("task-1")
            assert sb1 is sb2  # 复用
            assert mgr.active_count() == 1
        finally:
            await mgr.destroy_all()

    @pytest.mark.asyncio
    async def test_get_or_create_new(self):
        mgr = await self._make_manager()
        try:
            sb1 = await mgr.get_or_create("task-1")
            sb2 = await mgr.get_or_create("task-2")
            assert sb1 is not sb2
            assert mgr.active_count() == 2
        finally:
            await mgr.destroy_all()

    @pytest.mark.asyncio
    async def test_execute_one_step(self):
        mgr = await self._make_manager()
        try:
            result = await mgr.execute(
                "print('Hello from manager')", task_id="task-1"
            )
            assert result.success
            assert "Hello from manager" in result.output
        finally:
            await mgr.destroy_all()

    @pytest.mark.asyncio
    async def test_destroy_sandbox(self):
        mgr = await self._make_manager()
        sb = await mgr.create_sandbox(task_id="task-1")
        sandbox_id = sb.info.sandbox_id
        ok = await mgr.destroy_sandbox(sandbox_id)
        assert ok
        assert mgr.active_count() == 0

    @pytest.mark.asyncio
    async def test_destroy_task_sandbox(self):
        mgr = await self._make_manager()
        await mgr.create_sandbox(task_id="task-1")
        ok = await mgr.destroy_task_sandbox("task-1")
        assert ok
        assert mgr.active_count() == 0
        assert await mgr.get_sandbox("task-1") is None

    @pytest.mark.asyncio
    async def test_destroy_nonexistent(self):
        mgr = await self._make_manager()
        try:
            ok = await mgr.destroy_sandbox("nonexistent")
            assert not ok
        finally:
            await mgr.destroy_all()

    @pytest.mark.asyncio
    async def test_destroy_all(self):
        mgr = await self._make_manager()
        await mgr.create_sandbox(task_id="task-1")
        await mgr.create_sandbox(task_id="task-2")
        await mgr.create_sandbox(task_id="task-3")
        await mgr.destroy_all()
        assert mgr.active_count() == 0

    @pytest.mark.asyncio
    async def test_list_sandboxes(self):
        mgr = await self._make_manager()
        try:
            await mgr.create_sandbox(task_id="task-1")
            await mgr.create_sandbox(task_id="task-2")
            infos = mgr.list_sandboxes()
            assert len(infos) == 2
        finally:
            await mgr.destroy_all()

    @pytest.mark.asyncio
    async def test_stats(self):
        mgr = await self._make_manager()
        try:
            await mgr.create_sandbox(task_id="task-1")
            stats = mgr.stats()
            assert stats["active"] == 1
            assert stats["total_created"] == 1
        finally:
            await mgr.destroy_all()

    @pytest.mark.asyncio
    async def test_max_sandboxes(self):
        mgr = SandboxManager(max_sandboxes=3, idle_timeout_sec=999)
        try:
            for i in range(3):
                await mgr.create_sandbox(task_id=f"task-{i}")
            assert mgr.active_count() == 3
            # 第4个应驱逐空闲后创建
            await mgr.create_sandbox(task_id="task-4")
            assert mgr.active_count() <= 4  # 可能驱逐1个
        finally:
            await mgr.destroy_all()

    @pytest.mark.asyncio
    async def test_execute_multiple_tasks(self):
        mgr = await self._make_manager()
        try:
            results = await asyncio.gather(
                mgr.execute("print('task-a')", task_id="a"),
                mgr.execute("print('task-b')", task_id="b"),
                mgr.execute("print('task-c')", task_id="c"),
            )
            assert all(r.success for r in results)
            assert mgr.active_count() == 3
        finally:
            await mgr.destroy_all()

    @pytest.mark.asyncio
    async def test_task_isolation(self):
        """不同任务使用独立沙箱"""
        mgr = await self._make_manager()
        try:
            sb1 = await mgr.get_or_create("task-a")
            sb2 = await mgr.get_or_create("task-b")
            assert sb1 is not sb2
            assert sb1.info.sandbox_id != sb2.info.sandbox_id
        finally:
            await mgr.destroy_all()

    @pytest.mark.asyncio
    async def test_execute_with_security(self):
        """带安全策略的执行"""
        mgr = await self._make_manager()
        try:
            policy = SecurityPolicy(level=SecurityLevel.HIGH)
            result = await mgr.execute(
                "import os\nos.system('echo hack')",
                task_id="secure-task",
                security=policy,
            )
            assert not result.success
        finally:
            await mgr.destroy_all()

    @pytest.mark.asyncio
    async def test_create_sandbox_with_security(self):
        mgr = await self._make_manager()
        try:
            policy = SecurityPolicy(level=SecurityLevel.LOW, read_only=True)
            sb = await mgr.create_sandbox(
                task_id="ro-task",
                security=policy,
            )
            assert sb.config.security.read_only is True
            assert sb.config.security.level == SecurityLevel.LOW
        finally:
            await mgr.destroy_all()


# ═══════════════════════════════════════════════════════════════
# SandboxConfig & Models
# ═══════════════════════════════════════════════════════════════

class TestSandboxModels:
    """数据模型测试"""

    def test_config_default(self):
        config = SandboxConfig()
        assert config.sandbox_type == SandboxType.PYTHON
        assert config.security.level == SecurityLevel.MEDIUM

    def test_config_custom(self):
        config = SandboxConfig(
            sandbox_type=SandboxType.DOCKER,
            task_id="docker-1",
            labels={"env": "prod"},
            extra_env={"KEY": "VALUE"},
        )
        assert config.sandbox_type == SandboxType.DOCKER
        assert config.task_id == "docker-1"
        assert config.labels["env"] == "prod"

    def test_result_success(self):
        result = SandboxResult(
            success=True,
            output="hello",
            exit_code=0,
            duration_ms=100,
        )
        assert result.success
        assert result.truncated is False

    def test_result_truncated(self):
        result = SandboxResult(
            success=True,
            output="x" * 100_001,
        )
        assert result.truncated

    def test_sandbox_info(self):
        info = SandboxInfo(
            sandbox_id="sb-001",
            sandbox_type=SandboxType.PYTHON,
            status=SandboxStatus.RUNNING,
            task_id="task-1",
        )
        assert info.sandbox_id == "sb-001"
        assert info.status == SandboxStatus.RUNNING
        assert info.created_at  # 自动生成

    def test_sandbox_type_enum(self):
        assert SandboxType.PYTHON.value == "python"
        assert SandboxType.DOCKER.value == "docker"
        assert SandboxType.BROWSER.value == "browser"

    def test_sandbox_status_enum(self):
        assert SandboxStatus.IDLE.value == "idle"
        assert SandboxStatus.DESTROYED.value == "destroyed"
