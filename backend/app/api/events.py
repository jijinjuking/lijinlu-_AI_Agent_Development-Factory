"""
AI Runtime OS — Events API

SSE 实时流：
  GET  /events/stream          — 全局事件流（可按 task_id 过滤）

历史事件查询（W19 Event Replay）：
  GET  /events                 — 分页查询历史事件
  GET  /events/{event_id}      — 获取单个事件详情
  GET  /events/task/{task_id}  — 获取指定任务的所有事件（按时间排序）
  GET  /events/types           — 获取所有事件类型枚举值
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, asc, desc
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.sse_manager import sse_manager
from app.database import get_db
from app.models.event import Event

logger = logging.getLogger("ai_runtime_os.api.events")

router = APIRouter(prefix="/events", tags=["Events"])


# ══════════════════════════════════════════════════════════════
# SSE 实时事件流
# ══════════════════════════════════════════════════════════════

@router.get("/stream")
async def event_stream(task_id: Optional[str] = Query(None, description="按 task_id 过滤")):
    """SSE 事件流 — 支持全局或按 task 过滤"""
    conn_id, queue = await sse_manager.subscribe(task_id)

    async def generate():
        try:
            yield f"event: connected\ndata: {{\"conn_id\":\"{conn_id}\"}}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await sse_manager.unsubscribe(conn_id, task_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ══════════════════════════════════════════════════════════════
# 历史事件查询 — W19 Event Replay 基础数据接口
# ══════════════════════════════════════════════════════════════

def _event_to_dict(event: Event) -> dict:
    """将 Event ORM 对象序列化为 API 响应 dict"""
    return {
        "id": event.id,
        "task_id": str(event.task_id) if event.task_id else None,
        "event_type": event.event_type,
        "event_payload": event.event_payload or {},
        "produced_at": event.produced_at.isoformat() if event.produced_at else None,
        "produced_by": event.produced_by,
    }


@router.get("")
async def list_events(
    task_id: Optional[str] = Query(None, description="按 task_id 过滤"),
    event_type: Optional[str] = Query(None, description="按事件类型过滤"),
    produced_by: Optional[str] = Query(None, description="按生产者过滤"),
    limit: int = Query(100, ge=1, le=500, description="每页条数"),
    offset: int = Query(0, ge=0, description="分页偏移"),
    order: str = Query("asc", regex="^(asc|desc)$", description="时间排序方向"),
    db: AsyncSession = Depends(get_db),
):
    """
    分页查询历史事件记录。

    支持按 task_id、event_type、produced_by 过滤，
    并可控制时间排序方向（asc = 正向回放，desc = 最新优先）。
    """
    stmt = select(Event)
    count_stmt = select(func.count(Event.id))

    if task_id:
        stmt = stmt.where(Event.task_id == task_id)
        count_stmt = count_stmt.where(Event.task_id == task_id)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
        count_stmt = count_stmt.where(Event.event_type == event_type)
    if produced_by:
        stmt = stmt.where(Event.produced_by == produced_by)
        count_stmt = count_stmt.where(Event.produced_by == produced_by)

    order_func = asc if order == "asc" else desc
    stmt = stmt.order_by(order_func(Event.produced_at)).offset(offset).limit(limit)

    result = await db.execute(stmt)
    events = result.scalars().all()

    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    return {
        "events": [_event_to_dict(e) for e in events],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/types")
async def list_event_types(db: AsyncSession = Depends(get_db)):
    """获取数据库中已有的所有事件类型（去重）"""
    stmt = select(Event.event_type).distinct().order_by(Event.event_type)
    result = await db.execute(stmt)
    types = [row[0] for row in result.fetchall()]
    return {"event_types": types, "count": len(types)}


@router.get("/task/{task_id}")
async def get_task_events(
    task_id: str,
    event_type: Optional[str] = Query(None, description="按事件类型过滤"),
    limit: int = Query(500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
):
    """
    获取指定任务的所有事件，按时间升序排列（用于完整事件回放序列）。
    """
    stmt = (
        select(Event)
        .where(Event.task_id == task_id)
        .order_by(asc(Event.produced_at))
        .limit(limit)
    )
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)

    result = await db.execute(stmt)
    events = result.scalars().all()

    if not events and not event_type:
        # 检查 task 是否存在（避免误导 404）
        count_stmt = select(func.count(Event.id)).where(Event.task_id == task_id)
        count_result = await db.execute(count_stmt)
        count = count_result.scalar() or 0
        if count == 0:
            raise HTTPException(status_code=404, detail=f"No events found for task {task_id}")

    return {
        "task_id": task_id,
        "events": [_event_to_dict(e) for e in events],
        "count": len(events),
    }



@router.get('/stats')
async def get_event_stats(db: AsyncSession = Depends(get_db)):
    """获取事件统计信息"""
    # 总数
    total_result = await db.execute(select(func.count(Event.id)))
    total = total_result.scalar() or 0

    # 按 event_type 分组
    type_result = await db.execute(
        select(Event.event_type, func.count(Event.id))
        .group_by(Event.event_type)
    )
    by_type = {row[0]: row[1] for row in type_result.all()}

    # 按 produced_by 分组（Top 10）
    producer_result = await db.execute(
        select(Event.produced_by, func.count(Event.id))
        .where(Event.produced_by.isnot(None))
        .group_by(Event.produced_by)
        .order_by(func.count(Event.id).desc())
        .limit(10)
    )
    by_producer = {row[0]: row[1] for row in producer_result.all()}

    # 最近 24 小时
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_result = await db.execute(
        select(func.count(Event.id)).where(Event.produced_at >= since)
    )
    recent_24h = recent_result.scalar() or 0

    return {
        'total': total,
        'by_type': by_type,
        'by_producer': by_producer,
        'recent_24h': recent_24h,
    }

@router.get("/{event_id}")
async def get_event(event_id: int, db: AsyncSession = Depends(get_db)):
    """获取单个事件详情"""
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    return _event_to_dict(event)

