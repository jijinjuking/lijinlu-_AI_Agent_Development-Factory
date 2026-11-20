"""
Runtime Context — LangGraph context_schema 类型定义

允许节点通过 LangGraph 原生 `runtime: Runtime[Context]` 参数获取运行时上下文。
对应 Phase 2.3 / Phase 3 的 context_schema 注入功能。
"""
from __future__ import annotations

from typing import Any, Optional

from langgraph.runtime import Runtime as LangGraphRuntime
from pydantic import BaseModel, Field


class RuntimeContext(BaseModel):
    """
    LangGraph context_schema 类型。

    节点签名: def handler(state, config, *, writer, runtime: Runtime[RuntimeContext])
    使用: ctx = runtime.context; task_id = ctx["task_id"]
    """

    task_id: str = Field(..., description="任务 ID")
    workflow_id: str = Field(default="", description="工作流 ID")
    user_id: str = Field(default="", description="用户 ID")
    config: dict[str, Any] = Field(
        default_factory=dict, description="额外配置"
    )


def create_runtime_context(
    task_id: str = "",
    workflow_id: str = "",
    user_id: str = "",
    project_id: str = "",
    stream_mode: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    创建 LangGraph RuntimeContext dict，用于注入到 graph.astream() 的 context 参数。

    Usage:
        ctx = create_runtime_context(task_id="abc", workflow_id="wf-1")
        async for chunk in graph.astream(state, config, context=ctx):
            ...
    """
    return {
        "task_id": task_id,
        "workflow_id": workflow_id,
        "user_id": user_id,
        "project_id": project_id,
        "stream_mode": stream_mode or [],
        "metadata": metadata or {},
        "config": config or {},
    }
