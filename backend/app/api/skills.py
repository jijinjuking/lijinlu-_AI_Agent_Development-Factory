"""
Skills API — Skill 市场（真实数据库）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.skill import Skill
from app.schemas.mixed import SkillResponse
from app.api._orm import skill_to_dict

router = APIRouter()


@router.get("", response_model=list[SkillResponse])
async def list_skills(
    category: str | None = Query(None),
    installed: bool | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Skill)
    if category:
        stmt = stmt.where(Skill.category == category)
    if installed is not None:
        stmt = stmt.where(Skill.installed == installed)
    if q:
        stmt = stmt.where(Skill.name.ilike(f"%{q}%"))
    result = await db.execute(stmt)
    return [skill_to_dict(s) for s in result.scalars().all()]


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill_to_dict(s)


@router.post("/{skill_id}/install", response_model=SkillResponse)
async def install_skill(skill_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Skill not found")
    s.installed = True
    await db.commit()
    await db.refresh(s)
    return skill_to_dict(s)


@router.post("/{skill_id}/uninstall", response_model=SkillResponse)
async def uninstall_skill(skill_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Skill not found")
    s.installed = False
    await db.commit()
    await db.refresh(s)
    return skill_to_dict(s)
