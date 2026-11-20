"""
Dashboard API — 总览仪表盘（真实数据库聚合 + 周期趋势 + 多源活动流）
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.agent import Agent
from app.models.event import Event, LLMCall
from app.models.pipeline import PipelineRun
from app.schemas.common import StatCard, ActivityItem

router = APIRouter()


def _this_vs_prev_week(now: datetime):
    """返回 (本周起始, 上周起始, 上周结束)，用于周期对比"""
    # 本周一 00:00 → 现在
    this_start = now - timedelta(days=now.weekday())
    this_start = this_start.replace(hour=0, minute=0, second=0, microsecond=0)
    # 上周一 → 上周日
    prev_start = this_start - timedelta(days=7)
    prev_end = this_start  # 上周日 00:00 = 本周一 00:00
    return this_start, prev_start, prev_end


def _calc_trend(this_val: float, prev_val: float) -> float:
    """计算趋势百分比，分母为0时返回 0"""
    if prev_val == 0:
        return 0.0 if this_val == 0 else 100.0
    return round((this_val - prev_val) / prev_val * 100, 1)


@router.get("/stats", response_model=list[StatCard])
async def get_stats(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    this_start, prev_start, prev_end = _this_vs_prev_week(now)

    # ── 活跃 Agent 数（当前） ──
    active_agents = await db.execute(
        select(func.count()).where(Agent.status == "running")
    )
    active_count = active_agents.scalar() or 0

    # ── Pipeline 执行总数 + 周期对比 ──
    total_pipelines = await db.execute(select(func.count()).select_from(PipelineRun))
    pipeline_count = total_pipelines.scalar() or 0

    # 本周 Pipeline
    pipelines_this = await db.execute(
        select(func.count()).where(
            PipelineRun.started_at >= this_start
        ).select_from(PipelineRun)
    )
    # 上周 Pipeline
    pipelines_prev = await db.execute(
        select(func.count()).where(
            PipelineRun.started_at >= prev_start,
            PipelineRun.started_at < prev_end,
        ).select_from(PipelineRun)
    )

    # ── Token 消耗 ──
    total_tokens = await db.execute(
        select(func.coalesce(func.sum(LLMCall.total_tokens), 0))
    )
    tokens = total_tokens.scalar() or 0

    tokens_this = await db.execute(
        select(func.coalesce(func.sum(LLMCall.total_tokens), 0)).where(
            LLMCall.created_at >= this_start
        )
    )
    tokens_prev = await db.execute(
        select(func.coalesce(func.sum(LLMCall.total_tokens), 0)).where(
            LLMCall.created_at >= prev_start,
            LLMCall.created_at < prev_end,
        )
    )

    # ── 费用 ──
    total_cost = await db.execute(
        select(func.coalesce(func.sum(LLMCall.estimated_cost), 0))
    )
    cost = round(total_cost.scalar() or 0, 2)

    cost_this = await db.execute(
        select(func.coalesce(func.sum(LLMCall.estimated_cost), 0)).where(
            LLMCall.created_at >= this_start
        )
    )
    cost_prev = await db.execute(
        select(func.coalesce(func.sum(LLMCall.estimated_cost), 0)).where(
            LLMCall.created_at >= prev_start,
            LLMCall.created_at < prev_end,
        )
    )

    # ── 完成 / 失败任务数 ──
    completed_tasks_result = await db.execute(
        select(func.coalesce(func.sum(Agent.completed_tasks), 0))
    )
    completed = completed_tasks_result.scalar() or 0
    failed_tasks_result = await db.execute(
        select(func.coalesce(func.sum(Agent.failed_tasks), 0))
    )
    failed = failed_tasks_result.scalar() or 0

    total_tasks = completed + failed
    success_rate = round(completed / total_tasks * 100, 1) if total_tasks > 0 else 100.0

    # ── 计算 trends ──
    pipeline_trend = _calc_trend(
        pipelines_this.scalar() or 0, pipelines_prev.scalar() or 0
    )
    token_trend = _calc_trend(
        tokens_this.scalar() or 0, tokens_prev.scalar() or 0
    )
    cost_trend = _calc_trend(
        cost_this.scalar() or 0, cost_prev.scalar() or 0
    )

    # ── Token 格式化 ──
    if tokens >= 1_000_000:
        token_str = f"{tokens / 1_000_000:.1f}M"
    elif tokens >= 1000:
        token_str = f"{tokens / 1000:.0f}K"
    else:
        token_str = str(tokens)

    return [
        StatCard(
            key="agents", title="活跃 Agent", value=active_count, suffix="个",
            trend=0, trend_label="当前在线数", color="#1677ff",
        ),
        StatCard(
            key="pipelines", title="流程执行", value=pipeline_count, suffix="次",
            trend=pipeline_trend, trend_label="较上周", color="#52c41a",
        ),
        StatCard(
            key="tasks", title="完成任务", value=completed, suffix="个",
            trend=0, trend_label="累计完成", color="#722ed1",
        ),
        StatCard(
            key="tokens", title="Token 消耗", value=token_str, suffix="",
            trend=token_trend, trend_label="较上周", color="#fa8c16",
        ),
        StatCard(
            key="cost", title="累计费用", value=f"¥ {cost:.2f}", suffix="",
            trend=cost_trend, trend_label="较上周", color="#13c2c2",
        ),
        StatCard(
            key="success_rate", title="成功率", value=f"{success_rate}", suffix="%",
            trend=0, trend_label="累计成功率", color="#52c41a",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# 活动流 — 多源聚合
# ═══════════════════════════════════════════════════════════


def _pipeline_to_activity(run) -> ActivityItem:
    status = (
        "success" if run.status == "completed"
        else "failed" if run.status == "failed"
        else "running"
    )
    title_map = {
        "running": "流程运行中", "completed": "流程完成",
        "failed": "流程失败", "paused": "流程暂停",
    }
    return ActivityItem(
        id=str(run.id),
        type="pipeline_run",
        title=title_map.get(run.status, "流程执行"),
        description=f"{run.template_name} — {run.current_step or ''}",
        agent_name=run.triggered_by or "System",
        timestamp=run.started_at.isoformat() if run.started_at else "",
        status=status,
    )


def _llmcall_to_activity(call) -> ActivityItem:
    tk = call.total_tokens or 0
    if tk >= 1000:
        tk_str = f"{tk / 1000:.0f}K"
    else:
        tk_str = str(tk)
    cost_str = f"¥{call.estimated_cost:.4f}" if call.estimated_cost else "¥0"
    task_type = call.task_type or "LLM 调用"
    desc = f"{call.model} · {tk_str} tokens · {cost_str} · {task_type}"
    return ActivityItem(
        id=str(call.id),
        type="llm_call",
        title="模型调用",
        description=desc,
        agent_name=call.agent_name or "",
        timestamp=call.created_at.isoformat() if call.created_at else "",
        status="success",
    )


def _event_to_activity(ev) -> ActivityItem | None:
    event_type = ev.event_type or ""
    if "agent" in event_type.lower():
        type_tag = "agent_event"
        if "start" in event_type.lower():
            title = "Agent 启动"
            status = "running"
        elif "error" in event_type.lower() or "fail" in event_type.lower():
            title = "Agent 异常"
            status = "failed"
        elif "complete" in event_type.lower() or "finish" in event_type.lower():
            title = "Agent 完成"
            status = "success"
        else:
            title = f"Agent 事件: {event_type}"
            status = "running"
    else:
        return None
    desc = event_type
    payload = ev.event_payload or {}
    agent_name = str(payload.get("agent_name", "")) if isinstance(payload, dict) else ""
    return ActivityItem(
        id=f"ev-{ev.id}",
        type=type_tag,
        title=title,
        description=desc,
        agent_name=agent_name,
        timestamp=ev.produced_at.isoformat() if ev.produced_at else "",
        status=status,
    )


@router.get("/activities", response_model=list[ActivityItem])
async def get_activities(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    多源活动流 —— 合并 PipelineRun + LLMCall + Event，按时间倒序
    """
    activities: list[ActivityItem] = []

    # 1. Pipeline 运行记录
    p_stmt = (
        select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(limit)
    )
    p_result = await db.execute(p_stmt)
    for run in p_result.scalars():
        activities.append(_pipeline_to_activity(run))

    # 2. LLM 调用记录
    l_stmt = (
        select(LLMCall).order_by(LLMCall.created_at.desc()).limit(limit)
    )
    l_result = await db.execute(l_stmt)
    for call in l_result.scalars():
        activities.append(_llmcall_to_activity(call))

    # 3. Agent 相关事件
    e_stmt = (
        select(Event)
        .where(Event.event_type.ilike("%agent%"))
        .order_by(Event.produced_at.desc())
        .limit(limit)
    )
    e_result = await db.execute(e_stmt)
    for ev in e_result.scalars():
        act = _event_to_activity(ev)
        if act:
            activities.append(act)

    # 按时间倒序合并，取前 limit 条
    activities.sort(key=lambda a: a.timestamp, reverse=True)
    return activities[:limit]
