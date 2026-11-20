"""
Memory API — 三层记忆管理（真实数据库）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.memory import MemoryEntry
from app.schemas.mixed import MemoryResponse, MemoryCreate, MemoryStats
from app.api._orm import memory_to_dict

router = APIRouter()


@router.get("", response_model=list[MemoryResponse])
async def list_memories(
    layer: str | None = Query(None),
    importance: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(MemoryEntry)
    if layer:
        stmt = stmt.where(MemoryEntry.layer == layer)
    if importance:
        stmt = stmt.where(MemoryEntry.importance == importance)
    if q:
        stmt = stmt.where(
            MemoryEntry.title.ilike(f"%{q}%") | MemoryEntry.content.ilike(f"%{q}%")
        )
    stmt = stmt.order_by(MemoryEntry.updated_at.desc())
    result = await db.execute(stmt)
    return [memory_to_dict(m) for m in result.scalars().all()]


@router.get("/stats", response_model=MemoryStats)
async def memory_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            MemoryEntry.layer,
            func.count().label("cnt"),
            func.coalesce(func.sum(MemoryEntry.token_estimate), 0).label("tokens"),
        ).group_by(MemoryEntry.layer)
    )
    rows = {r.layer: (r.cnt, r.tokens) for r in result.all()}
    return MemoryStats(
        cloud_count=rows.get("cloud", (0,))[0],
        user_count=rows.get("user", (0,))[0],
        project_count=rows.get("project", (0,))[0],
        total_tokens=sum(v[1] for v in rows.values()),
    )


@router.post("", response_model=MemoryResponse, status_code=201)
async def create_memory(body: MemoryCreate, db: AsyncSession = Depends(get_db)):
    mem = MemoryEntry(
        layer=body.layer,
        title=body.title,
        content=body.content,
        tags=",".join(body.tags) if body.tags else "",
        importance=body.importance,
        token_estimate=len(body.content) // 4 if body.content else 0,
    )
    db.add(mem)
    await db.commit()
    await db.refresh(mem)
    return memory_to_dict(mem)


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MemoryEntry).where(MemoryEntry.id == memory_id))
    mem = result.scalar_one_or_none()
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    await db.delete(mem)
    await db.commit()
    return {"status": "deleted"}
