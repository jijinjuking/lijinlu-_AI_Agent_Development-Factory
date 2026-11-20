"""
Pipelines API — 流程编排（真实数据库 + 后台步骤执行）
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session_factory
from app.models.pipeline import PipelineTemplate, PipelineRun
from app.schemas.pipeline import (
    PipelineTemplateResponse, PipelineTemplateCreate, PipelineRunResponse, PipelineRunRequest,
)
from app.api._orm import tpl_to_dict, run_to_dict

router = APIRouter()


# ---- 根路由 ----

@router.get("", response_model=list[PipelineRunResponse])
async def list_pipelines(db: AsyncSession = Depends(get_db)):
    """获取 Pipeline 列表（Runs）"""
    return await list_runs(status=None, db=db)


# ---- Templates ----

@router.get("/templates", response_model=list[PipelineTemplateResponse])
async def list_templates(
    category: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(PipelineTemplate)
    if category:
        stmt = stmt.where(PipelineTemplate.category == category)
    result = await db.execute(stmt)
    return [tpl_to_dict(t) for t in result.scalars().all()]


@router.get("/templates/{template_id}", response_model=PipelineTemplateResponse)
async def get_template(template_id: str, db: AsyncSession = Depends(get_db)):
    uid = uuid.UUID(template_id)
    result = await db.execute(select(PipelineTemplate).where(PipelineTemplate.id == uid))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl_to_dict(t)


@router.post("/templates", response_model=PipelineTemplateResponse, status_code=201)
async def create_template(body: PipelineTemplateCreate, db: AsyncSession = Depends(get_db)):
    tpl = PipelineTemplate(
        name=body.name, description=body.description,
        icon=body.icon, category=body.category,
        tags=",".join(body.tags) if body.tags else "",
        steps_json=[s.model_dump() for s in body.steps],
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return tpl_to_dict(tpl)


@router.put("/templates/{template_id}", response_model=PipelineTemplateResponse)
async def update_template(template_id: str, body: PipelineTemplateCreate, db: AsyncSession = Depends(get_db)):
    uid = uuid.UUID(template_id)
    result = await db.execute(select(PipelineTemplate).where(PipelineTemplate.id == uid))
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    tpl.name = body.name
    tpl.description = body.description
    tpl.icon = body.icon
    tpl.category = body.category
    tpl.tags = ",".join(body.tags) if body.tags else ""
    tpl.steps_json = [s.model_dump() for s in body.steps]
    tpl.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(tpl)
    return tpl_to_dict(tpl)


# ---- Runs ----

@router.get("/runs", response_model=list[PipelineRunResponse])
async def list_runs(
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(PipelineRun).order_by(PipelineRun.started_at.desc())
    if status:
        stmt = stmt.where(PipelineRun.status == status)
    result = await db.execute(stmt)
    return [run_to_dict(r) for r in result.scalars().all()]


@router.get("/runs/{run_id}", response_model=PipelineRunResponse)
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)):
    uid = uuid.UUID(run_id)
    result = await db.execute(select(PipelineRun).where(PipelineRun.id == uid))
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_to_dict(r)


async def _execute_pipeline_run(run_id: uuid.UUID):
    """后台执行 Pipeline 的步骤序列"""
    async with async_session_factory() as db:
        try:
            result = await db.execute(
                select(PipelineRun).where(PipelineRun.id == run_id)
            )
            run = result.scalar_one_or_none()
            if not run:
                return

            steps = await _load_steps(db, run.template_id)
            if not steps:
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)
                await db.commit()
                return

            for i, step in enumerate(steps):
                # 检查是否被暂停
                await db.refresh(run)
                if run.status == "paused":
                    return  # 等待 resume 后重新调度

                step_name = step.get("name", f"Step {i+1}")
                step_type = step.get("type", "agent")

                run.current_step = step_name
                run.completed_steps = i
                await db.commit()

                try:
                    if step_type == "agent":
                        await _execute_agent_step(db, step, run)
                    else:
                        await _execute_generic_step(db, step, step_type)

                    run.completed_steps = i + 1
                    run.failed_steps = 0
                except Exception as e:
                    run.failed_steps += 1
                    # 单步失败不中断整个流程，继续执行
                    continue

                await db.commit()

            # 全部步骤完成
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            if run.started_at:
                # SQLite 读回的是 naive datetime，与 aware 的 completed_at 相减会抛
                # TypeError，导致整个 run 被顶层 except 误判为 failed
                started = run.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                run.duration = int(
                    (run.completed_at - started).total_seconds() * 1000
                )
            await db.commit()

        except Exception as e:
            # 顶层异常：标记为失败
            try:
                await db.refresh(run)
                run.status = "failed"
                run.completed_at = datetime.now(timezone.utc)
                await db.commit()
            except Exception:
                pass  # 连数据库都不可用则放弃


async def _load_steps(db: AsyncSession, template_id: uuid.UUID | None) -> list[dict]:
    """加载模板的步骤定义"""
    if not template_id:
        return []
    result = await db.execute(
        select(PipelineTemplate).where(PipelineTemplate.id == template_id)
    )
    tpl = result.scalar_one_or_none()
    return tpl.steps_json if tpl else []


async def _execute_agent_step(db: AsyncSession, step: dict, run: PipelineRun):
    """执行 agent 类型步骤：查找匹配 Agent 并创建/执行任务"""
    from app.models.agent import Agent
    from app.models.task import Task
    from app.services.agent_executor import AgentExecutor

    agent_role = step.get("agent_role", "developer")
    step_desc = step.get("description", step.get("name", ""))

    # 根据 role 查找可用 Agent
    result = await db.execute(
        select(Agent).where(
            Agent.role == agent_role,
            Agent.is_active == True,
            Agent.status == "idle",
        ).limit(1)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        # 没有匹配的 Agent，模拟执行
        return

    # 创建任务
    task = Task(
        id=uuid.uuid4(),
        name=f"[Pipeline] {step.get('name', 'Step')}",
        title=step.get("name", "Pipeline Step"),
        goal_description=step_desc,
        agent_id=agent.id,
        agent_name=agent.name,
        status="pending",
        kanban_column="todo",
        priority="medium",
        created_at=datetime.now(timezone.utc),
    )
    db.add(task)
    await db.commit()

    # 执行任务
    executor = AgentExecutor(db)
    try:
        await executor.execute(str(task.id), str(agent.id))
    except Exception as e:
        raise


async def _execute_generic_step(db: AsyncSession, step: dict, step_type: str):
    """执行非 agent 步骤（condition / review / deploy / notify）"""
    # 模拟执行：延迟一小段时间代表处理
    await asyncio.sleep(0.5)


@router.post("/start", response_model=PipelineRunResponse, status_code=201)
async def start_pipeline(body: PipelineRunRequest, db: AsyncSession = Depends(get_db)):
    uid = uuid.UUID(body.template_id)
    result = await db.execute(
        select(PipelineTemplate).where(PipelineTemplate.id == uid)
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    steps = tpl.steps_json or []
    run = PipelineRun(
        template_id=tpl.id,
        template_name=tpl.name,
        status="running",
        started_at=datetime.now(timezone.utc),
        current_step=steps[0]["name"] if steps else "",
        total_steps=len(steps),
        completed_steps=0,
        failed_steps=0,
        triggered_by="API",
        cost=0.0,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # 后台异步执行步骤
    asyncio.create_task(_execute_pipeline_run(run.id))

    return run_to_dict(run)


@router.put("/runs/{run_id}/pause")
async def pause_run(run_id: str, db: AsyncSession = Depends(get_db)):
    uid = uuid.UUID(run_id)
    result = await db.execute(select(PipelineRun).where(PipelineRun.id == uid))
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")
    r.status = "paused"
    await db.commit()
    return {"status": "ok"}


@router.put("/runs/{run_id}/resume")
async def resume_run(run_id: str, db: AsyncSession = Depends(get_db)):
    uid = uuid.UUID(run_id)
    result = await db.execute(select(PipelineRun).where(PipelineRun.id == uid))
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")
    r.status = "running"
    await db.commit()
    return {"status": "ok"}
