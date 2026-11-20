"""
Tool Executor — 统一执行入口
所有 Tool 调用必须经过此入口：
Permission → Sandbox → Timeout → Adapter → Trace → Audit
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.runtime.tool_runtime.models import (
    ExecutionContext,
    ExecutionResult,
    ExecutionStatus,
    PermissionLevel,
    ToolInfo,
)
from app.runtime.tool_runtime.registry import tool_registry
from app.runtime.tool_runtime.permission import PermissionEngine
from app.runtime.tool_runtime.audit import AuditLogger
from app.runtime.tool_runtime.timeout import TimeoutHandler
from app.runtime.tool_runtime.tracer import ToolTracer
from app.runtime.tool_runtime.sandbox import ProcessSandbox

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    统一工具执行器
    执行流程: 查找 → 权限 → 沙箱 → 超时 → 适配器 → 追踪 → 审计
    """

    def __init__(self, db: AsyncSession | None = None, registry: "ToolRegistry | None" = None, sandbox_manager=None):
        self.registry = registry if registry is not None else tool_registry
        self.permission = PermissionEngine()
        self.audit = AuditLogger(db)
        self.timeout = TimeoutHandler()
        self.tracer = ToolTracer()
        self.db = db
        self.sandbox_manager = sandbox_manager

    async def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Optional[ExecutionContext] = None,
    ) -> ExecutionResult:
        """
        执行工具调用 — 统一入口

        Args:
            tool_name: 工具名称
            args: 工具参数
            context: 执行上下文（task_id, agent_id, permission_level 等）

        Returns:
            ExecutionResult: 执行结果
        """
        if context is None:
            context = ExecutionContext()

        # 1. 查找工具
        tool_info = self.registry.get(tool_name)
        if not tool_info:
            return ExecutionResult(
                tool_name=tool_name,
                status=ExecutionStatus.FAILED,
                error=f"工具 '{tool_name}' 未注册",
            )

        # 2. 权限检查
        perm_result = self.permission.check(tool_info, context)
        if perm_result:
            await self.audit.log(tool_name, perm_result, args, context.task_id, context.agent_id)
            return perm_result

        # 3. 参数校验
        validation_errors = self._validate_args(args, tool_info.parameters_schema)
        if validation_errors:
            return ExecutionResult(
                tool_name=tool_name,
                status=ExecutionStatus.FAILED,
                error="; ".join(validation_errors),
            )

        # 4. 沙箱准备
        sandbox = None
        if tool_info.sandbox_required:
            if self.sandbox_manager:
                # 使用配置的沙箱管理器
                sandbox = await self.sandbox_manager.create_sandbox()
                logger.debug("Sandbox created via sandbox_manager for tool '%s': %s", tool_name, sandbox.sandbox_id)
            else:
                # 使用默认沙箱
                sandbox = ProcessSandbox()
                logger.debug("Sandbox created for tool '%s': %s", tool_name, sandbox.sandbox_id)

        # 5. 开始追踪
        trace_id = self.tracer.start_trace(tool_name, args, context)

        # 6. 执行（带超时控制）
        adapter = tool_info.adapter
        if not adapter:
            return ExecutionResult(
                tool_name=tool_name,
                status=ExecutionStatus.FAILED,
                error=f"工具 '{tool_name}' 没有关联的适配器",
            )

        timeout_sec = tool_info.timeout_sec

        try:
            result = await self.timeout.execute_with_timeout(
                adapter(args, context),
                timeout_sec=timeout_sec,
                tool_name=tool_name,
                on_timeout=lambda: sandbox.cleanup() if sandbox else None,
            )

            if isinstance(result, ExecutionResult):
                final_result = result
            else:
                final_result = ExecutionResult(
                    tool_name=tool_name,
                    status=ExecutionStatus.COMPLETED,
                    output=str(result),
                )

        except Exception as e:
            logger.exception("Tool '%s' execution error", tool_name)
            final_result = ExecutionResult(
                tool_name=tool_name,
                status=ExecutionStatus.FAILED,
                error=f"执行异常: {type(e).__name__}: {str(e)}",
            )

        # 7. 结束追踪
        self.tracer.end_trace(trace_id, final_result)

        # 8. 审计日志
        await self.audit.log(
            tool_name,
            final_result,
            args,
            context.task_id,
            context.agent_id,
        )

        # 9. 清理沙箱
        if sandbox:
            sandbox.cleanup()

        return final_result

    async def execute_batch(
        self,
        calls: list[Dict[str, Any]],
        context: Optional[ExecutionContext] = None,
    ) -> list[ExecutionResult]:
        """
        批量执行工具调用（顺序执行）
        """
        results = []
        for call in calls:
            tool_name = call.get("tool_name", "")
            args = call.get("args", {})
            result = await self.execute(tool_name, args, context)
            results.append(result)
        return results

    def get_available_tools(
        self,
        context: Optional[ExecutionContext] = None,
    ) -> list[ToolInfo]:
        """获取当前上下文可用的工具列表"""
        all_tools = self.registry.list_all()
        if context:
            return self.permission.get_allowed_tools(all_tools, context)
        return all_tools

    def get_tool_schema_for_llm(
        self,
        context: Optional[ExecutionContext] = None,
    ) -> list[Dict[str, Any]]:
        """
        生成 OpenAI Function Calling 格式的工具定义
        可用于注入到 LLM 请求中
        """
        tools = self.get_available_tools(context)
        schemas = []

        for tool in tools:
            schema = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or tool.display_name,
                    "parameters": tool.parameters_schema,
                },
            }
            schemas.append(schema)

        return schemas

    def _validate_args(self, args: Dict[str, Any], schema: Dict) -> list[str]:
        """校验参数"""
        errors: list[str] = []
        if "required" in schema:
            for req in schema["required"]:
                if req not in args or args[req] is None:
                    errors.append(f"缺少必填参数: {req}")
        return errors


# 全局默认执行器实例（方便直接引用）
default_executor: Optional[ToolExecutor] = None


def get_executor(db: AsyncSession | None = None) -> ToolExecutor:
    """获取/创建 ToolExecutor 实例"""
    global default_executor
    if db:
        return ToolExecutor(db)
    if default_executor is None:
        default_executor = ToolExecutor()
    return default_executor
