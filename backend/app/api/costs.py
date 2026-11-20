"""
Costs API — 成本分析（真实数据库，从 llm_calls 聚合）
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import LLMCall
from app.schemas.mixed import (
    CostSummaryResponse, CostRecordResponse,
    ModelCostSummaryResponse, AgentCostSummaryResponse,
    CostTrendResponse, ModelPricingResponse,
)
from app.api._orm import llmcall_to_dict

router = APIRouter()


# ---- 根路由 ----

@router.get("", response_model=CostSummaryResponse)
async def cost_index(db: AsyncSession = Depends(get_db)):
    """成本概览"""
    return await cost_summary(db=db)


# 定价信息（静态，Phase 2 可从数据库读取）
_PRICING: list[dict] = [
    {"model": "gpt-4o", "provider": "OpenAI", "input_price": 0.035, "output_price": 0.105},
    {"model": "gpt-4o-mini", "provider": "OpenAI", "input_price": 0.0015, "output_price": 0.006},
    {"model": "claude-3.5-sonnet", "provider": "Anthropic", "input_price": 0.021, "output_price": 0.105},
    {"model": "claude-3-opus", "provider": "Anthropic", "input_price": 0.105, "output_price": 0.525},
    {"model": "qwen2.5-72b", "provider": "Local/Ollama", "input_price": 0, "output_price": 0},
]


@router.get("/summary", response_model=CostSummaryResponse)
async def cost_summary(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    month_start = today_start.replace(day=1)

    # 今天
    today = await db.execute(
        select(func.coalesce(func.sum(LLMCall.estimated_cost), 0),
               func.coalesce(func.sum(LLMCall.total_tokens), 0))
        .where(LLMCall.created_at >= today_start)
    )
    today_cost, today_tokens = today.one()

    # 本月
    month = await db.execute(
        select(func.coalesce(func.sum(LLMCall.estimated_cost), 0),
               func.coalesce(func.sum(LLMCall.total_tokens), 0))
        .where(LLMCall.created_at >= month_start)
    )
    month_cost, month_tokens = month.one()

    # 总计
    total = await db.execute(
        select(func.coalesce(func.sum(LLMCall.estimated_cost), 0),
               func.coalesce(func.sum(LLMCall.total_tokens), 0))
    )
    total_cost, total_tokens = total.one()

    # 周汇总
    week = await db.execute(
        select(func.coalesce(func.sum(LLMCall.estimated_cost), 0))
        .where(LLMCall.created_at >= week_start)
    )
    week_cost = week.scalar() or 0.0

    # Top Agent
    top = await db.execute(
        select(LLMCall.agent_name, func.sum(LLMCall.estimated_cost).label("tc"))
        .group_by(LLMCall.agent_name)
        .order_by(func.sum(LLMCall.estimated_cost).desc())
        .limit(1)
    )
    top_row = top.one_or_none()
    top_agent = top_row.agent_name if top_row else ""
    top_agent_cost = round(top_row.tc, 2) if top_row and top_row.tc else 0.0

    return CostSummaryResponse(
        today_cost=round(today_cost, 2),
        week_cost=round(week_cost, 2),
        month_cost=round(month_cost, 2),
        total_cost=round(total_cost, 2),
        today_tokens=int(today_tokens),
        month_tokens=int(month_tokens),
        total_tokens=int(total_tokens),
        top_agent=top_agent,
        top_agent_cost=top_agent_cost,
    )


@router.get("/records", response_model=list[CostRecordResponse])
async def cost_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(LLMCall).order_by(LLMCall.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size)
    result = await db.execute(stmt)
    return [llmcall_to_dict(c) for c in result.scalars().all()]


@router.get("/by-model", response_model=list[ModelCostSummaryResponse])
async def cost_by_model(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            LLMCall.model,
            func.coalesce(func.sum(LLMCall.total_tokens), 0).label("tokens"),
            func.coalesce(func.sum(LLMCall.estimated_cost), 0).label("cost"),
            func.count().label("cnt"),
        ).group_by(LLMCall.model)
    )
    rows = result.all()
    total = sum(r.cost for r in rows)
    return [
        ModelCostSummaryResponse(
            model=r.model,
            total_tokens=int(r.tokens),
            total_cost=round(r.cost, 2),
            call_count=r.cnt,
            percentage=round(r.cost / total * 100, 1) if total > 0 else 0,
        )
        for r in rows
    ]


@router.get("/by-agent", response_model=list[AgentCostSummaryResponse])
async def cost_by_agent(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            LLMCall.agent_name,
            func.coalesce(func.sum(LLMCall.total_tokens), 0).label("tokens"),
            func.coalesce(func.sum(LLMCall.estimated_cost), 0).label("cost"),
            func.count().label("cnt"),
        ).group_by(LLMCall.agent_name).order_by(func.sum(LLMCall.estimated_cost).desc())
    )
    return [
        AgentCostSummaryResponse(
            agent_id="", agent_name=r.agent_name or "",
            total_tokens=int(r.tokens), total_cost=round(r.cost, 2),
            task_count=r.cnt,
        )
        for r in result.all()
    ]


@router.get("/trend", response_model=list[CostTrendResponse])
async def cost_trend(days: int = Query(7, ge=1, le=90), db: AsyncSession = Depends(get_db)):
    # 按天聚合
    result = await db.execute(
        select(
            func.date(LLMCall.created_at).label("d"),
            func.coalesce(func.sum(LLMCall.estimated_cost), 0).label("cost"),
            func.coalesce(func.sum(LLMCall.total_tokens), 0).label("tokens"),
        ).group_by(func.date(LLMCall.created_at))
        .order_by(func.date(LLMCall.created_at).desc())
        .limit(days)
    )
    rows = list(result.all())
    rows.reverse()  # 升序
    return [
        CostTrendResponse(
            date=r.d.isoformat() if hasattr(r.d, 'isoformat') else str(r.d),
            cost=round(r.cost, 2),
            tokens=int(r.tokens),
        )
        for r in rows
    ]


@router.get("/pricing", response_model=list[ModelPricingResponse])
async def model_pricing():
    return _PRICING
