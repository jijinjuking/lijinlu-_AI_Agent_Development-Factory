"""
AI Runtime OS — Task API（Kanban 看板后端）
提供：Task CRUD + Kanban 列视图 + 任务执行触发 + 取消
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session_factory
from app.models.task import Task
from app.schemas.task import TaskCreate, TaskUpdate
from app.api._orm import task_to_dict, COLUMN_MAP
from app.core.sse_manager import sse_manager
from app.api.auth import get_current_user
from app.models.user import User

logger = logging.getLogger("ai_runtime_os.tasks")
router = APIRouter()

# ── 执行追踪 ──
_active_executions: dict[str, asyncio.Task] = {}
MAX_CONCURRENT_EXECUTIONS = 5


# ========== Kanban 看板专用 ==========

@router.get("/kanban")
async def get_kanban_board(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """返回 KanbanColumn[] 数组，每列包含 type/title/tasks。"""
    result = await db.execute(select(Task))
    tasks = result.scalars().all()

    columns = {
        "todo":          {"id": "col-todo",          "type": "todo",          "title": "待办",   "tasks": []},
        "in_progress":  {"id": "col-in-progress",  "type": "in_progress",  "title": "进行中", "tasks": []},
        "review":        {"id": "col-review",        "type": "review",        "title": "审查中", "tasks": []},
        "done":          {"id": "col-done",          "type": "done",          "title": "已完成", "tasks": []},
        "failed":        {"id": "col-failed",        "type": "failed",        "title": "已失败", "tasks": []},
    }

    for t in tasks:
        d = task_to_dict(t)
        raw_col = t.kanban_column or "todo"
        col_key = COLUMN_MAP.get(raw_col, raw_col)
        col = columns.get(col_key, columns["todo"])
        col["tasks"].append(d)

    return list(columns.values())


@router.get("/executions")
async def list_executions(current_user: User = Depends(get_current_user)):
    """列出当前正在运行的任务。"""
    return {
        "active_count": len(_active_executions),
        "max_concurrent": MAX_CONCURRENT_EXECUTIONS,
        "task_ids": list(_active_executions.keys()),
    }


# ========== 普通 CRUD ==========

@router.get("")
async def list_tasks(
    status: str | None = Query(None),
    kanban_column: str | None = Query(None),
    agent_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Task)
    if status:
        stmt = stmt.where(Task.status == status)
    if kanban_column:
        stmt = stmt.where(Task.kanban_column == kanban_column)
    if agent_id:
        uid = uuid.UUID(agent_id)
        stmt = stmt.where(Task.agent_id == uid)
    result = await db.execute(stmt)
    return [task_to_dict(t) for t in result.scalars().all()]


@router.get("/{task_id}")
async def get_task(task_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    uid = uuid.UUID(task_id)
    result = await db.execute(select(Task).where(Task.id == uid))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    return task_to_dict(t)


@router.post("", status_code=201)
async def create_task(body: TaskCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    agent_id = uuid.UUID(body.agent_id) if body.agent_id else None
    t = Task(
        name=body.name,
        goal_description=body.goal_description or "",
        title=body.title or body.name,
        kanban_column="todo",
        agent_id=agent_id,
        priority=body.priority,
        tags=",".join(body.tags) if body.tags else "",
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return task_to_dict(t)


@router.put("/{task_id}")
async def update_task(task_id: str, body: TaskUpdate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    uid = uuid.UUID(task_id)
    result = await db.execute(select(Task).where(Task.id == uid))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")

    data = body.model_dump(exclude_unset=True)
    # 防御：agent_id 变更时自动查表填充 agent_name（如果调用方未提供）
    auto_agent_name = False
    if "agent_id" in data and data["agent_id"] and "agent_name" not in data:
        auto_agent_name = True
    # 如果调用方显式传了 agent_name=""，也视为需要自动填充
    if "agent_id" in data and data.get("agent_name") == "" and data["agent_id"]:
        auto_agent_name = True

    for k, v in data.items():
        if k == "tags" and isinstance(v, list):
            v = ",".join(v)
        if k == "agent_id" and v:
            v = uuid.UUID(v)
        setattr(t, k, v)

    # 自动填充 agent_name
    if auto_agent_name and t.agent_id:
        try:
            from app.models.agent import Agent
            r = await db.execute(select(Agent).where(Agent.id == t.agent_id))
            agent = r.scalar_one_or_none()
            if agent:
                t.agent_name = agent.name
        except Exception:
            pass

    await db.commit()
    await db.refresh(t)
    return task_to_dict(t)


@router.delete("/{task_id}")
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    uid = uuid.UUID(task_id)
    result = await db.execute(select(Task).where(Task.id == uid))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.delete(t)
    await db.commit()
    return {"status": "deleted"}


# ========== 任务执行 ==========

_NOT_EXECUTABLE = frozenset({"running", "completed", "cancelled"})


async def _run_executor(task_id: str, agent_id: str):
    """后台执行任务，使用独立 db session。完成后从追踪表清除。"""
    try:
        async with async_session_factory() as db:
            from app.services.agent_executor import AgentExecutor
            executor = AgentExecutor(db)
            await executor.execute(task_id, agent_id)
    except Exception:
        logger.exception("Task %s execution failed", task_id)
    finally:
        _active_executions.pop(task_id, None)


@router.post("/{task_id}/execute")
async def execute_task(task_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """触发 Agent 执行任务。后台执行，立即返回。"""
    uid = uuid.UUID(task_id)
    result = await db.execute(select(Task).where(Task.id == uid))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if not t.agent_id:
        raise HTTPException(status_code=400, detail="Task has no assigned agent")
    if t.status in _NOT_EXECUTABLE:
        raise HTTPException(status_code=409, detail=f"Task is already {t.status}")
    if len(_active_executions) >= MAX_CONCURRENT_EXECUTIONS:
        raise HTTPException(status_code=429, detail="Too many concurrent executions")

    # 标记为 running
    t.status = "running"
    t.started_at = datetime.now(timezone.utc)
    await db.commit()

    # 后台执行，存入追踪表
    bg_task = asyncio.create_task(_run_executor(task_id, str(t.agent_id)))
    _active_executions[task_id] = bg_task

    logger.info("Task %s execution started (agent=%s, active=%d)", task_id, t.agent_id, len(_active_executions))
    return {"status": "started", "task_id": task_id}


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """取消正在执行的任务。"""
    uid = uuid.UUID(task_id)
    result = await db.execute(select(Task).where(Task.id == uid))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if t.status != "running":
        raise HTTPException(status_code=409, detail=f"Task is not running (current: {t.status})")

    bg_task = _active_executions.get(task_id)
    if bg_task and not bg_task.done():
        bg_task.cancel()
        logger.info("Task %s cancelled", task_id)

    t.status = "cancelled"
    t.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(t)

    _active_executions.pop(task_id, None)

    # 广播 SSE 事件
    await sse_manager.publish("task_cancelled", {
        "task_id": task_id,
        "task": task_to_dict(t),
    }, task_id=task_id)

    return {"status": "cancelled", "task_id": task_id}
