"""
Tool Runtime — 核心数据类
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional


class PermissionLevel(str, Enum):
    """工具权限级别"""
    READONLY = "readonly"   # 只读操作（安全）
    NORMAL = "normal"       # 普通操作（默认）
    ELEVATED = "elevated"   # 需要审批
    RESTRICTED = "restricted"  # 仅管理员


class ExecutionStatus(str, Enum):
    """执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    DENIED = "denied"


@dataclass
class ToolInfo:
    """工具注册信息"""
    name: str
    display_name: str = ""
    description: str = ""
    adapter_type: str = "shell"
    version: str = "1.0.0"
    author: str = ""
    tags: list[str] = field(default_factory=list)
    parameters_schema: dict = field(default_factory=dict)
    sandbox_required: bool = False
    timeout_sec: int = 60
    max_retries: int = 2
    permission_level: PermissionLevel = PermissionLevel.NORMAL
    adapter: Optional[Callable] = None  # adapter function reference


@dataclass
class ExecutionContext:
    """执行上下文 — 传递给每个工具调用"""
    task_id: str | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    permission_level: PermissionLevel = PermissionLevel.NORMAL
    metadata: dict = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """工具执行结果"""
    tool_name: str
    status: ExecutionStatus
    output: str | None = None
    error: str | None = None
    exit_code: int | None = None
    duration_ms: int = 0
    sandbox_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class AuditEntry:
    """审计日志条目"""
    tool_name: str
    status: ExecutionStatus
    task_id: str | None = None
    agent_id: str | None = None
    input_args: dict = field(default_factory=dict)
    output_summary: str | None = None
    error: str | None = None
    duration_ms: int = 0
    exit_code: int | None = None
    timestamp: Optional[str] = None
