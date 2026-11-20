"""
Tool Adapter 基础抽象
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from app.runtime.tool_runtime.models import ExecutionContext, ExecutionResult


class BaseAdapter(ABC):
    """所有 Tool Adapter 的抽象基类"""

    @abstractmethod
    async def execute(
        self,
        args: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionResult:
        """执行工具调用，返回 ExecutionResult"""
        ...

    def validate_args(self, args: Dict[str, Any], schema: Dict) -> list[str]:
        """
        校验参数是否符合 JSON Schema
        返回错误列表，空列表表示校验通过
        """
        errors: list[str] = []
        if "required" in schema:
            for req in schema["required"]:
                if req not in args:
                    errors.append(f"缺少必填参数: {req}")
        return errors
