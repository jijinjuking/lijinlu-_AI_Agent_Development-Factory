"""
Tool Registry — 工具注册表
管理所有已注册的 Tool，提供注册/注销/查询功能
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from app.runtime.tool_runtime.models import ToolInfo, PermissionLevel

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    工具注册表
    默认使用单例模式，但也可创建独立实例（用于测试）
    """

    _instance: Optional["ToolRegistry"] = None

    def __new__(cls, use_singleton: bool = True) -> "ToolRegistry":
        if use_singleton and cls._instance is not None:
            return cls._instance
        instance = super().__new__(cls)
        instance._tools: Dict[str, ToolInfo] = {}
        if use_singleton:
            cls._instance = instance
        return instance

    def register(self, info: ToolInfo) -> None:
        """注册一个工具"""
        if info.name in self._tools:
            logger.warning("Tool '%s' already registered, overwriting", info.name)
        self._tools[info.name] = info
        logger.info("Tool registered: %s (adapter=%s, level=%s)", info.name, info.adapter_type, info.permission_level)

    def unregister(self, name: str) -> bool:
        """注销一个工具"""
        if name in self._tools:
            del self._tools[name]
            logger.info("Tool unregistered: %s", name)
            return True
        return False

    def get(self, name: str) -> Optional[ToolInfo]:
        """获取工具信息"""
        return self._tools.get(name)

    def list_all(self) -> List[ToolInfo]:
        """列出所有已注册工具"""
        return list(self._tools.values())

    def list_by_type(self, adapter_type: str) -> List[ToolInfo]:
        """按适配器类型筛选"""
        return [t for t in self._tools.values() if t.adapter_type == adapter_type]

    def list_by_permission(self, level: PermissionLevel) -> List[ToolInfo]:
        """按权限级别筛选"""
        return [t for t in self._tools.values() if t.permission_level == level]

    def has(self, name: str) -> bool:
        """检查工具是否已注册"""
        return name in self._tools

    def count(self) -> int:
        """已注册工具数量"""
        return len(self._tools)

    def clear(self) -> None:
        """清空所有注册"""
        self._tools.clear()
        logger.info("Tool registry cleared")

    def register_builtins(self) -> None:
        """注册内置工具（Shell / Git / Python）"""
        from app.runtime.tool_runtime.adapters.shell_adapter import shell_execute
        from app.runtime.tool_runtime.adapters.git_adapter import git_execute
        from app.runtime.tool_runtime.adapters.python_adapter import python_execute

        # Shell
        self.register(ToolInfo(
            name="shell_exec",
            display_name="Shell 命令执行",
            description="在沙箱环境中执行 Shell 命令。支持常见的文件操作、系统查询等。",
            adapter_type="shell",
            parameters_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 Shell 命令"},
                    "cwd": {"type": "string", "description": "工作目录（可选）"},
                    "env": {"type": "object", "description": "环境变量（可选）"},
                },
                "required": ["command"],
            },
            permission_level=PermissionLevel.NORMAL,
            timeout_sec=30,
            adapter=shell_execute,
        ))

        # Git
        self.register(ToolInfo(
            name="git_operation",
            display_name="Git 操作",
            description="执行 Git 操作：clone/pull/push/commit/status/log/branch 等。",
            adapter_type="git",
            parameters_schema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["clone", "pull", "push", "commit", "status", "log", "branch", "checkout", "diff", "merge"],
                        "description": "Git 操作类型",
                    },
                    "repo_url": {"type": "string", "description": "仓库 URL（clone 时必填）"},
                    "branch": {"type": "string", "description": "分支名称"},
                    "message": {"type": "string", "description": "提交信息（commit 时使用）"},
                    "files": {"type": "array", "items": {"type": "string"}, "description": "要操作的文件列表"},
                },
                "required": ["operation"],
            },
            permission_level=PermissionLevel.ELEVATED,
            timeout_sec=60,
            adapter=git_execute,
        ))

        # Python
        self.register(ToolInfo(
            name="python_exec",
            display_name="Python 代码执行",
            description="在受限沙箱中安全执行 Python 代码片段。禁止文件系统写入、网络访问等危险操作。",
            adapter_type="python",
            parameters_schema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要执行的 Python 代码"},
                    "timeout_sec": {"type": "integer", "description": "超时时间（秒），默认 10"},
                },
                "required": ["code"],
            },
            permission_level=PermissionLevel.NORMAL,
            timeout_sec=10,
            max_retries=1,
            adapter=python_execute,
        ))

        logger.info("Built-in tools registered: shell_exec, git_operation, python_exec")


# 全局单例
tool_registry = ToolRegistry()
