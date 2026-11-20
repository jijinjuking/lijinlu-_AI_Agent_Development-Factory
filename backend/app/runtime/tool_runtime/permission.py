"""
Permission Engine — 权限检查引擎
管控哪些 Tool 可以被调用，支持四级权限体系
"""
from __future__ import annotations

import logging
from typing import Optional

from app.runtime.tool_runtime.models import (
    ExecutionContext,
    ExecutionResult,
    ExecutionStatus,
    PermissionLevel,
    ToolInfo,
)

logger = logging.getLogger(__name__)

# 权限层级权重
_PERMISSION_WEIGHTS = {
    PermissionLevel.READONLY: 0,
    PermissionLevel.NORMAL: 10,
    PermissionLevel.ELEVATED: 50,
    PermissionLevel.RESTRICTED: 100,
}


class PermissionEngine:
    """
    权限引擎 — 检查调用者是否有权限执行指定 Tool
    """

    def check(
        self,
        tool_info: ToolInfo,
        context: ExecutionContext,
    ) -> Optional[ExecutionResult]:
        """
        检查权限。返回 None 表示通过；返回 ExecutionResult 表示被拒绝。
        """

        # RESTRICTED 工具：仅允许管理员上下文
        if tool_info.permission_level == PermissionLevel.RESTRICTED:
            if context.permission_level != PermissionLevel.RESTRICTED:
                return ExecutionResult(
                    tool_name=tool_info.name,
                    status=ExecutionStatus.DENIED,
                    error=f"工具 '{tool_info.name}' 需要管理员权限 (RESTRICTED)，当前权限级别: {context.permission_level}",
                )

        # ELEVATED 工具：需要 ELEVATED 或更高
        if tool_info.permission_level == PermissionLevel.ELEVATED:
            if _PERMISSION_WEIGHTS.get(context.permission_level, 0) < _PERMISSION_WEIGHTS[PermissionLevel.ELEVATED]:
                return ExecutionResult(
                    tool_name=tool_info.name,
                    status=ExecutionStatus.DENIED,
                    error=f"工具 '{tool_info.name}' 需要提升权限 (ELEVATED)，当前权限级别: {context.permission_level}",
                )

        # 禁用检查
        if hasattr(tool_info, 'enabled') and not getattr(tool_info, 'enabled', True):
            return ExecutionResult(
                tool_name=tool_info.name,
                status=ExecutionStatus.DENIED,
                error=f"工具 '{tool_info.name}' 已被禁用",
            )

        return None  # 通过

    def get_allowed_tools(
        self,
        tools: list[ToolInfo],
        context: ExecutionContext,
    ) -> list[ToolInfo]:
        """过滤出当前上下文可用的工具列表"""
        allowed = []
        for tool in tools:
            if self.check(tool, context) is None:
                allowed.append(tool)
        return allowed
