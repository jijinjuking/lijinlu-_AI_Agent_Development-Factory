"""
API Routes — Tool Runtime
GET  /tools              — 列出所有已注册工具
GET  /tools/{name}       — 获取工具详情
POST /tools/{name}/execute — 执行工具
GET  /tools/audit         — 审计日志
GET  /tools/audit/stats   — 审计统计
GET  /tools/traces        — 追踪记录
GET  /tools/traces/stats  — 追踪统计
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.runtime.tool_runtime.registry import tool_registry
from app.runtime.tool_runtime.executor import ToolExecutor
from app.runtime.tool_runtime.tracer import ToolTracer
from app.runtime.tool_runtime.audit import AuditLogger
from app.runtime.tool_runtime.models import ExecutionContext, PermissionLevel

router = APIRouter()

# 确保内置工具已注册
if tool_registry.count() == 0:
    tool_registry.register_builtins()


# ── Request/Response Models ──

class ToolExecuteRequest(BaseModel):
    args: dict = Field(default_factory=dict)
    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    permission_level: str = "normal"


class ToolListItem(BaseModel):
    name: str
    display_name: str
    description: str
    adapter_type: str
    permission_level: str
    version: str
    timeout_sec: int
    sandbox_required: bool
    parameters_schema: dict


class ToolDetail(ToolListItem):
    tags: list[str]
    author: str
    max_retries: int


class ToolExecuteResponse(BaseModel):
    tool_name: str
    status: str
    output: Optional[str] = None
    error: Optional[str] = None
    exit_code: Optional[int] = None
    duration_ms: int


# ── Routes ──

@router.get("", response_model=list[ToolListItem])
async def list_tools(
    adapter_type: Optional[str] = Query(None),
    permission_level: Optional[str] = Query(None),
):
    """列出所有已注册工具"""
    tools = tool_registry.list_all()

    if adapter_type:
        tools = [t for t in tools if t.adapter_type == adapter_type]
    if permission_level:
        tools = [t for t in tools if t.permission_level.value == permission_level]

    return [
        ToolListItem(
            name=t.name,
            display_name=t.display_name,
            description=t.description,
            adapter_type=t.adapter_type,
            permission_level=t.permission_level.value,
            version=t.version,
            timeout_sec=t.timeout_sec,
            sandbox_required=t.sandbox_required,
            parameters_schema=t.parameters_schema,
        )
        for t in tools
    ]


@router.get("/{name}", response_model=ToolDetail)
async def get_tool(name: str):
    """获取工具详情"""
    tool = tool_registry.get(name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")

    return ToolDetail(
        name=tool.name,
        display_name=tool.display_name,
        description=tool.description,
        adapter_type=tool.adapter_type,
        permission_level=tool.permission_level.value,
        version=tool.version,
        timeout_sec=tool.timeout_sec,
        sandbox_required=tool.sandbox_required,
        parameters_schema=tool.parameters_schema,
        tags=tool.tags,
        author=tool.author,
        max_retries=tool.max_retries,
    )


@router.post("/{name}/execute", response_model=ToolExecuteResponse)
async def execute_tool(
    name: str,
    body: ToolExecuteRequest,
    db: AsyncSession = Depends(get_db),
):
    """执行工具"""
    perm_level = PermissionLevel.NORMAL
    try:
        perm_level = PermissionLevel(body.permission_level)
    except ValueError:
        pass

    context = ExecutionContext(
        task_id=body.task_id,
        agent_id=body.agent_id,
        permission_level=perm_level,
    )

    executor = ToolExecutor(db)
    result = await executor.execute(name, body.args, context)

    return ToolExecuteResponse(
        tool_name=result.tool_name,
        status=result.status.value if hasattr(result.status, 'value') else str(result.status),
        output=result.output,
        error=result.error,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
    )


@router.get("/audit/list")
async def list_audit_logs(
    limit: int = Query(50, ge=1, le=500),
    tool_name: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取审计日志"""
    audit = AuditLogger(db)
    logs = await audit.get_from_db(db, limit=limit, tool_name=tool_name, task_id=task_id)
    return {"logs": logs, "count": len(logs)}


@router.get("/audit/stats")
async def get_audit_stats(
    db: AsyncSession = Depends(get_db),
):
    """获取审计统计"""
    audit = AuditLogger(db)
    return await audit.get_stats(db)


@router.get("/traces/list")
async def list_traces(
    limit: int = Query(50, ge=1, le=500),
    tool_name: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
):
    """获取追踪记录"""
    tracer = ToolTracer()
    traces = tracer.get_traces(limit=limit, tool_name=tool_name, task_id=task_id)
    return {"traces": traces, "count": len(traces)}


@router.get("/traces/stats")
async def get_trace_stats():
    """获取追踪统计"""
    tracer = ToolTracer()
    return tracer.get_stats()
