"""
Tool Runtime 单元测试
覆盖：Registry / Permission / Audit / Executor / API
"""
import json
import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_db, async_session_factory
from app.runtime.tool_runtime.registry import ToolRegistry
from app.runtime.tool_runtime.registry import tool_registry
from app.runtime.tool_runtime.models import (
    ToolInfo, ExecutionContext, ExecutionResult, ExecutionStatus, PermissionLevel,
)
from app.runtime.tool_runtime.permission import PermissionEngine
from app.runtime.tool_runtime.executor import ToolExecutor


# ── Tool Registry Tests ──

class TestToolRegistry:
    """测试 ToolRegistry — 使用独立实例，不污染全局单例"""

    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        """每个测试使用独立 registry"""
        self.registry = ToolRegistry(use_singleton=False)

    def test_register_and_get(self):
        info = ToolInfo(
            name="test_tool",
            display_name="Test Tool",
            description="A test tool",
            adapter_type="shell",
        )
        self.registry.register(info)

        assert self.registry.count() == 1
        assert self.registry.has("test_tool")
        fetched = self.registry.get("test_tool")
        assert fetched is not None
        assert fetched.name == "test_tool"
        assert fetched.display_name == "Test Tool"

    def test_unregister(self):
        self.registry.register(ToolInfo(name="temp_tool"))
        assert self.registry.count() == 1

        assert self.registry.unregister("temp_tool") is True
        assert self.registry.count() == 0
        assert self.registry.unregister("nonexistent") is False

    def test_list_all(self):
        self.registry.register(ToolInfo(name="tool_a"))
        self.registry.register(ToolInfo(name="tool_b"))

        tools = self.registry.list_all()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"tool_a", "tool_b"}

    def test_list_by_type(self):
        self.registry.register(ToolInfo(name="s1", adapter_type="shell"))
        self.registry.register(ToolInfo(name="s2", adapter_type="shell"))
        self.registry.register(ToolInfo(name="g1", adapter_type="git"))

        shells = self.registry.list_by_type("shell")
        assert len(shells) == 2
        gits = self.registry.list_by_type("git")
        assert len(gits) == 1
        pys = self.registry.list_by_type("python")
        assert len(pys) == 0

    def test_list_by_permission(self):
        self.registry.register(ToolInfo(name="r1", permission_level=PermissionLevel.READONLY))
        self.registry.register(ToolInfo(name="n1", permission_level=PermissionLevel.NORMAL))
        self.registry.register(ToolInfo(name="e1", permission_level=PermissionLevel.ELEVATED))

        assert len(self.registry.list_by_permission(PermissionLevel.READONLY)) == 1
        assert len(self.registry.list_by_permission(PermissionLevel.NORMAL)) == 1
        assert len(self.registry.list_by_permission(PermissionLevel.ELEVATED)) == 1
        assert len(self.registry.list_by_permission(PermissionLevel.RESTRICTED)) == 0

    def test_register_builtins(self):
        self.registry.register_builtins()

        assert self.registry.has("shell_exec")
        assert self.registry.has("git_operation")
        assert self.registry.has("python_exec")

        shell = self.registry.get("shell_exec")
        assert shell is not None
        assert shell.parameters_schema["required"] == ["command"]

        git = self.registry.get("git_operation")
        assert git is not None
        assert git.permission_level == PermissionLevel.ELEVATED

    def test_register_overwrite(self):
        self.registry.register(ToolInfo(name="dup", display_name="First"))
        assert self.registry.count() == 1

        self.registry.register(ToolInfo(name="dup", display_name="Second"))
        assert self.registry.count() == 1
        assert self.registry.get("dup").display_name == "Second"


# ── Permission Engine Tests ──

class TestPermissionEngine:
    """测试 PermissionEngine"""

    def test_normal_tool_allowed(self):
        engine = PermissionEngine()
        tool = ToolInfo(name="test", permission_level=PermissionLevel.NORMAL)
        ctx = ExecutionContext(permission_level=PermissionLevel.NORMAL)

        result = engine.check(tool, ctx)
        assert result is None  # 通过

    def test_readonly_tool_allowed_for_normal(self):
        engine = PermissionEngine()
        tool = ToolInfo(name="test", permission_level=PermissionLevel.READONLY)
        ctx = ExecutionContext(permission_level=PermissionLevel.NORMAL)

        result = engine.check(tool, ctx)
        assert result is None

    def test_elevated_tool_denied_for_normal(self):
        engine = PermissionEngine()
        tool = ToolInfo(name="test", permission_level=PermissionLevel.ELEVATED)
        ctx = ExecutionContext(permission_level=PermissionLevel.NORMAL)

        result = engine.check(tool, ctx)
        assert result is not None
        assert result.status == ExecutionStatus.DENIED

    def test_elevated_tool_allowed_for_elevated(self):
        engine = PermissionEngine()
        tool = ToolInfo(name="test", permission_level=PermissionLevel.ELEVATED)
        ctx = ExecutionContext(permission_level=PermissionLevel.ELEVATED)

        result = engine.check(tool, ctx)
        assert result is None

    def test_restricted_tool_denied_for_elevated(self):
        engine = PermissionEngine()
        tool = ToolInfo(name="test", permission_level=PermissionLevel.RESTRICTED)
        ctx = ExecutionContext(permission_level=PermissionLevel.ELEVATED)

        result = engine.check(tool, ctx)
        assert result is not None
        assert result.status == ExecutionStatus.DENIED

    def test_restricted_tool_allowed_for_restricted(self):
        engine = PermissionEngine()
        tool = ToolInfo(name="test", permission_level=PermissionLevel.RESTRICTED)
        ctx = ExecutionContext(permission_level=PermissionLevel.RESTRICTED)

        result = engine.check(tool, ctx)
        assert result is None

    def test_disabled_tool_denied(self):
        engine = PermissionEngine()
        tool = ToolInfo(name="test", permission_level=PermissionLevel.NORMAL)
        tool.enabled = False
        ctx = ExecutionContext(permission_level=PermissionLevel.NORMAL)

        result = engine.check(tool, ctx)
        assert result is not None
        assert result.status == ExecutionStatus.DENIED

    def test_get_allowed_tools(self):
        engine = PermissionEngine()
        tools = [
            ToolInfo(name="r", permission_level=PermissionLevel.READONLY),
            ToolInfo(name="n", permission_level=PermissionLevel.NORMAL),
            ToolInfo(name="e", permission_level=PermissionLevel.ELEVATED),
        ]
        ctx = ExecutionContext(permission_level=PermissionLevel.NORMAL)

        allowed = engine.get_allowed_tools(tools, ctx)
        assert len(allowed) == 2
        names = {t.name for t in allowed}
        assert names == {"r", "n"}


# ── Tool Executor Tests ──

@pytest.fixture
def test_registry():
    """创建一个干净的 registry 用于测试"""
    registry = ToolRegistry(use_singleton=False)

    # 注册一个 mock 工具
    async def mock_adapter(args, ctx):
        return ExecutionResult(
            tool_name="mock_tool",
            status=ExecutionStatus.COMPLETED,
            output=f"Mock executed with args: {args}",
        )

    registry.register(ToolInfo(
        name="mock_tool",
        display_name="Mock Tool",
        description="A mock tool for testing",
        adapter_type="shell",
        parameters_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        permission_level=PermissionLevel.NORMAL,
        timeout_sec=5,
        adapter=mock_adapter,
    ))

    # 注册一个限制权限的工具
    async def restricted_adapter(args, ctx):
        return ExecutionResult(
            tool_name="restricted_tool",
            status=ExecutionStatus.COMPLETED,
            output="Restricted access",
        )

    registry.register(ToolInfo(
        name="restricted_tool",
        display_name="Restricted Tool",
        adapter_type="shell",
        permission_level=PermissionLevel.ELEVATED,
        timeout_sec=5,
        adapter=restricted_adapter,
    ))

    return registry


class TestToolExecutor:
    """测试 ToolExecutor"""

    def test_execute_success(self, test_registry):
        executor = ToolExecutor(registry=test_registry)

        import asyncio
        result = asyncio.run(executor.execute(
            "mock_tool",
            {"message": "hello"},
            ExecutionContext(permission_level=PermissionLevel.NORMAL),
        ))

        assert result.status == ExecutionStatus.COMPLETED
        assert "hello" in (result.output or "")

    def test_execute_not_found(self, test_registry):
        executor = ToolExecutor(registry=test_registry)

        import asyncio
        result = asyncio.run(executor.execute(
            "nonexistent",
            {},
            ExecutionContext(),
        ))

        assert result.status == ExecutionStatus.FAILED
        assert "未注册" in (result.error or "")

    def test_execute_permission_denied(self, test_registry):
        executor = ToolExecutor(registry=test_registry)

        import asyncio
        result = asyncio.run(executor.execute(
            "restricted_tool",
            {},
            ExecutionContext(permission_level=PermissionLevel.NORMAL),
        ))

        assert result.status == ExecutionStatus.DENIED

    def test_execute_missing_required_args(self, test_registry):
        executor = ToolExecutor(registry=test_registry)

        import asyncio
        result = asyncio.run(executor.execute(
            "mock_tool",
            {},
            ExecutionContext(),
        ))

        assert result.status == ExecutionStatus.FAILED
        assert "message" in (result.error or "")

    def test_get_available_tools(self, test_registry):
        executor = ToolExecutor(registry=test_registry)

        # 普通权限只能看到 mock_tool
        ctx = ExecutionContext(permission_level=PermissionLevel.NORMAL)
        tools = executor.get_available_tools(ctx)
        assert len(tools) == 1
        assert tools[0].name == "mock_tool"

        # 提升权限可以看到两个
        ctx_elevated = ExecutionContext(permission_level=PermissionLevel.ELEVATED)
        tools_elevated = executor.get_available_tools(ctx_elevated)
        assert len(tools_elevated) == 2

    def test_get_tool_schema_for_llm(self, test_registry):
        executor = ToolExecutor(registry=test_registry)

        schemas = executor.get_tool_schema_for_llm(
            ExecutionContext(permission_level=PermissionLevel.ELEVATED),
        )

        assert len(schemas) == 2
        assert schemas[0]["type"] == "function"
        assert "function" in schemas[0]
        assert schemas[0]["function"]["name"] in ("mock_tool", "restricted_tool")


# ── Tool API Tests ──

class TestToolAPI:
    """测试 /api/v1/tools 端点"""

    @pytest.fixture(autouse=True)
    def _ensure_builtins(self):
        """确保全局单例中内置工具已注册"""
        if tool_registry.count() == 0:
            tool_registry.register_builtins()

    @pytest.mark.asyncio
    async def test_list_tools(self, client):
        resp = await client.get("/tools")
        assert resp.status_code == 200
        tools = resp.json()
        assert isinstance(tools, list)
        assert len(tools) >= 3  # shell_exec, git_operation, python_exec
        names = {t["name"] for t in tools}
        assert "shell_exec" in names
        assert "git_operation" in names
        assert "python_exec" in names

    @pytest.mark.asyncio
    async def test_list_tools_filter_by_type(self, client):
        resp = await client.get("/tools?adapter_type=shell")
        assert resp.status_code == 200
        tools = resp.json()
        assert all(t["adapter_type"] == "shell" for t in tools)

    @pytest.mark.asyncio
    async def test_get_tool_detail(self, client):
        resp = await client.get("/tools/shell_exec")
        assert resp.status_code == 200
        tool = resp.json()
        assert tool["name"] == "shell_exec"
        assert tool["adapter_type"] == "shell"
        assert "parameters_schema" in tool

    @pytest.mark.asyncio
    async def test_get_tool_not_found(self, client):
        resp = await client.get("/tools/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_execute_shell_tool(self, client):
        resp = await client.post(
            "/tools/shell_exec/execute",
            json={"args": {"command": "echo hello_tool"}},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["tool_name"] == "shell_exec"
        assert result["status"] == "completed"
        assert "hello_tool" in (result.get("output") or "")

    @pytest.mark.asyncio
    async def test_execute_shell_dangerous_blocked(self, client):
        resp = await client.post(
            "/tools/shell_exec/execute",
            json={"args": {"command": "rm -rf /"}},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "denied"

    @pytest.mark.asyncio
    async def test_execute_python_tool(self, client):
        resp = await client.post(
            "/tools/python_exec/execute",
            json={"args": {"code": "x = 1 + 2\nprint(x)"}},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "completed"
        assert "3" in (result.get("output") or "")

    @pytest.mark.asyncio
    async def test_execute_python_forbidden(self, client):
        resp = await client.post(
            "/tools/python_exec/execute",
            json={"args": {"code": "eval('1+1')"}},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "denied"

    @pytest.mark.asyncio
    async def test_execute_missing_args(self, client):
        resp = await client.post(
            "/tools/shell_exec/execute",
            json={"args": {}},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_audit_stats(self, client):
        resp = await client.get("/tools/audit/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert "total" in stats
        assert "completed" in stats
        assert "failed" in stats

    @pytest.mark.asyncio
    async def test_trace_stats(self, client):
        resp = await client.get("/tools/traces/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert "total" in stats


# ── Tool Model Tests ──

class TestToolModels:
    """测试数据类"""

    def test_tool_info_defaults(self):
        info = ToolInfo(name="test")
        assert info.display_name == ""
        assert info.version == "1.0.0"
        assert info.timeout_sec == 60
        assert info.permission_level == PermissionLevel.NORMAL
        assert info.tags == []

    def test_execution_result(self):
        result = ExecutionResult(
            tool_name="test",
            status=ExecutionStatus.COMPLETED,
            output="done",
            duration_ms=100,
        )
        assert result.tool_name == "test"
        assert result.status == ExecutionStatus.COMPLETED
        assert result.output == "done"
        assert result.error is None

    def test_execution_context(self):
        ctx = ExecutionContext(
            task_id="t1",
            agent_id="a1",
            permission_level=PermissionLevel.ELEVATED,
        )
        assert ctx.task_id == "t1"
        assert ctx.agent_id == "a1"
        assert ctx.permission_level == PermissionLevel.ELEVATED
