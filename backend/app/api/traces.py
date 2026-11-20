"""
Traces API — 执行追踪

从 PipelineRun + PipelineTemplate.steps_json 动态生成 Trace 节点，
不再使用硬编码 demo 数据。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.pipeline import PipelineRun, PipelineTemplate
from app.schemas.trace import TraceListItem, TraceResponse, TraceNodeResponse

router = APIRouter()


# ── Trace 节点生成 ──────────────────────────────────────────────────────────


def _determine_step_status(
    step_index: int,
    run_status: str,
    completed_steps: int,
    failed_steps: int,
    current_step: str | None,
    step_name: str,
) -> str:
    """根据 run 状态推断单个 step 的执行状态"""
    if run_status in ("failed", "cancelled"):
        if step_index < completed_steps:
            return "success"
        if step_index == completed_steps:
            return "failed" if run_status == "failed" else "cancelled"
        return "pending"
    if run_status == "completed":
        return "success"
    # running / paused
    if current_step and step_name == current_step:
        return "running"
    if step_index < completed_steps:
        return "success"
    return "pending"


def _build_trace_nodes(run, template) -> list[dict]:
    """从 PipelineTemplate.steps_json 动态生成 trace 节点"""
    if not template or not template.steps_json:
        return []

    nodes: list[dict] = []
    steps = template.steps_json
    root_id = f"trace-{run.id}-root"

    # 根节点：整个 Pipeline
    root = {
        "id": root_id,
        "parent_id": None,
        "type": "chain",
        "name": run.template_name or "Unnamed Pipeline",
        "status": run.status,
        "start_time": run.started_at.isoformat() if run.started_at else None,
        "end_time": run.completed_at.isoformat() if run.completed_at else None,
        "duration": run.duration or 0,
        "input": "",
        "output": "",
        "children": [],
    }
    nodes.append(root)

    for i, step in enumerate(steps):
        step_name = step.get("name", f"Step {i + 1}")
        step_id = f"trace-{run.id}-step-{i}"
        agent_name = step.get("agent_name", "")

        status = _determine_step_status(
            i, run.status, run.completed_steps, run.failed_steps,
            run.current_step, step_name,
        )

        node = {
            "id": step_id,
            "parent_id": root_id,
            "type": "agent_action",
            "name": step_name,
            "status": status,
            "start_time": run.started_at.isoformat() if run.started_at else None,
            "end_time": run.completed_at.isoformat()
            if status == "success" and run.completed_at
            else None,
            "duration": 0,
            "input": step.get("description", ""),
            "output": step_name if status == "success" else "",
            "agent_name": agent_name,
            "children": [],
        }
        root["children"].append(step_id)
        nodes.append(node)

    return nodes


# ── 端点 ────────────────────────────────────────────────────────────────────


def _run_to_trace(run) -> dict:
    """PipelineRun → TraceListItem"""
    return {
        "id": str(run.id),
        "pipeline_name": run.template_name,
        "agent_name": run.triggered_by or "",
        "status": run.status,
        "start_time": run.started_at.isoformat() if run.started_at else "",
        "duration": run.duration or None,
        "total_tokens": 0,
        "total_cost": run.cost or 0.0,
    }


@router.get("", response_model=list[TraceListItem])
async def list_traces(
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(PipelineRun)
        .order_by(PipelineRun.started_at.desc())
        .limit(20)
    )
    if status:
        stmt = stmt.where(PipelineRun.status == status)
    result = await db.execute(stmt)
    return [_run_to_trace(r) for r in result.scalars().all()]


@router.get("/{trace_id}", response_model=TraceResponse)
async def get_trace(trace_id: str, db: AsyncSession = Depends(get_db)):
    trace_uuid = uuid.UUID(trace_id)
    result = await db.execute(
        select(PipelineRun).where(PipelineRun.id == trace_uuid)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Trace not found")

    # 加载模板以获得步骤结构
    nodes: list[dict] = []
    template = None
    if run.template_id:
        t_result = await db.execute(
            select(PipelineTemplate).where(
                PipelineTemplate.id == run.template_id
            )
        )
        template = t_result.scalar_one_or_none()

    nodes = _build_trace_nodes(run, template)

    return TraceResponse(
        id=str(run.id),
        pipeline_id=str(run.template_id) if run.template_id else "",
        pipeline_name=run.template_name,
        agent_id="",
        agent_name=run.triggered_by or "",
        start_time=run.started_at.isoformat() if run.started_at else "",
        end_time=run.completed_at.isoformat() if run.completed_at else None,
        duration=run.duration or None,
        status=run.status,
        total_tokens=0,
        total_cost=run.cost or 0.0,
        node_count=len(nodes),
        error_count=sum(1 for n in nodes if n.get("status") == "failed"),
        root_node_id=nodes[0]["id"] if nodes else "",
        nodes=nodes,
    )


@router.get("/{trace_id}/nodes", response_model=list[TraceNodeResponse])
async def get_trace_nodes(trace_id: str, db: AsyncSession = Depends(get_db)):
    trace_uuid = uuid.UUID(trace_id)
    result = await db.execute(
        select(PipelineRun).where(PipelineRun.id == trace_uuid)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Trace not found")

    template = None
    if run.template_id:
        t_result = await db.execute(
            select(PipelineTemplate).where(
                PipelineTemplate.id == run.template_id
            )
        )
        template = t_result.scalar_one_or_none()

    nodes = _build_trace_nodes(run, template)
    if not nodes:
        raise HTTPException(status_code=404, detail="No trace nodes found")
    return nodes
