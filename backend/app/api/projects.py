"""
AI Runtime OS — Project API（项目管理）
"""
from __future__ import annotations

import logging
import uuid as uuid_module

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate

logger = logging.getLogger("ai_runtime_os.projects")
router = APIRouter()


@router.get("/")
async def list_projects(
    status: str = Query("", description="按状态过滤"),
    member_id: str = Query("", description="按成员过滤"),
    db: AsyncSession = Depends(get_db),
):
    """获取所有项目（可选过滤）"""
    stmt = select(Project)
    if status:
        stmt = stmt.where(Project.status == status)
    if member_id:
        stmt = stmt.where(Project.created_by == member_id)
    stmt = stmt.order_by(Project.updated_at.desc())
    result = await db.execute(stmt)
    projects = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description or "",
            "status": p.status,
            "created_by": p.created_by or "",
            "created_at": p.created_at.isoformat() if p.created_at else "",
            "updated_at": p.updated_at.isoformat() if p.updated_at else "",
        }
        for p in projects
    ]


@router.post("/")
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建新项目"""
    project = Project(
        name=body.name,
        description=body.description,
        status=body.status,
        created_by="李金路",
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description or "",
        "status": project.status,
        "created_by": project.created_by or "",
        "created_at": project.created_at.isoformat() if project.created_at else "",
        "updated_at": project.updated_at.isoformat() if project.updated_at else "",
    }


@router.get("/{project_id}")
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """获取项目详情"""
    try:
        uid = uuid_module.UUID(project_id)
    except ValueError:
        raise HTTPException(400, f"无效的 project_id: {project_id}")

    result = await db.execute(select(Project).where(Project.id == uid))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")

    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description or "",
        "status": project.status,
        "created_by": project.created_by or "",
        "created_at": project.created_at.isoformat() if project.created_at else "",
        "updated_at": project.updated_at.isoformat() if project.updated_at else "",
    }


@router.patch("/{project_id}")
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新项目"""
    try:
        uid = uuid_module.UUID(project_id)
    except ValueError:
        raise HTTPException(400, f"无效的 project_id: {project_id}")

    result = await db.execute(select(Project).where(Project.id == uid))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(project, field, value)

    await db.commit()
    await db.refresh(project)

    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description or "",
        "status": project.status,
        "created_by": project.created_by or "",
        "created_at": project.created_at.isoformat() if project.created_at else "",
        "updated_at": project.updated_at.isoformat() if project.updated_at else "",
    }


@router.delete("/{project_id}")
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """删除项目"""
    try:
        uid = uuid_module.UUID(project_id)
    except ValueError:
        raise HTTPException(400, f"无效的 project_id: {project_id}")

    result = await db.execute(select(Project).where(Project.id == uid))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")

    await db.delete(project)
    await db.commit()
    return {"id": project_id, "deleted": True}
