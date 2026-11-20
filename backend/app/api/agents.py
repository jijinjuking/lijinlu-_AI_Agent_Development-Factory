"""
Agents API — Agent 管理（真实数据库 + LLM 集成）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.agent import Agent
from app.models.settings import AgentPermission
from app.schemas.agent import AgentResponse, AgentCreate, AgentUpdate, AgentStatusUpdate
from app.api._orm import agent_to_dict
from app.services.llm_service import llm_service
from app.api.auth import get_current_user
from app.models.user import User
import uuid

router = APIRouter()


async def _ensure_permission(db: AsyncSession, role: str) -> None:
    """确保角色在 agent_permissions 中存在，不存在则插入默认权限记录。"""
    if not role:
        return
    result = await db.execute(
        select(AgentPermission).where(AgentPermission.role_id == role)
    )
    if result.scalar_one_or_none() is not None:
        return
    # 新角色：用保守默认权限（用户可在权限 Tab 里自行调整）
    db.add(AgentPermission(
        role_id=role,
        role_name=role,  # 默认用 role_id 作为显示名，用户可编辑
        can_create_pipeline=False,
        can_deploy=False,
        can_access_network=True,
        can_write_files=True,
        can_execute_commands=False,
        max_concurrency=2,
        max_tokens_per_task=30000,
        max_daily_cost=10.0,
    ))
    await db.flush()


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    status: str | None = Query(None),
    role: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Agent)
    if status:
        stmt = stmt.where(Agent.status == status)
    if role:
        stmt = stmt.where(Agent.role == role)
    result = await db.execute(stmt)
    return [agent_to_dict(a) for a in result.scalars().all()]


@router.get("/{id}", response_model=AgentResponse)
async def get_agent(id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    uid = uuid.UUID(id)
    result = await db.execute(select(Agent).where(Agent.id == uid))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {id} not found")
    return agent_to_dict(agent)


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(body: AgentCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    existing = await db.execute(select(Agent).where(Agent.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Agent name already exists")
    # 自动初始化角色权限（如不存在）
    await _ensure_permission(db, body.role)
    agent = Agent(
        name=body.name, role=body.role, model=body.model,
        model_mode=body.model_mode,
        description=body.description, system_prompt=body.system_prompt,
        capability_tags=body.capability_tags,
        max_retries=body.max_retries, timeout_sec=body.timeout_sec,
        is_active=body.is_active,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent_to_dict(agent)


@router.put("/{id}", response_model=AgentResponse)
async def update_agent(id: str, body: AgentUpdate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    uid = uuid.UUID(id)
    result = await db.execute(select(Agent).where(Agent.id == uid))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {id} not found")
    # 如果更新了角色，确保新角色有权限记录
    if body.role is not None:
        await _ensure_permission(db, body.role)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(agent, k, v)
    await db.commit()
    await db.refresh(agent)
    return agent_to_dict(agent)


@router.delete("/{id}")
async def delete_agent(id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    uid = uuid.UUID(id)
    result = await db.execute(select(Agent).where(Agent.id == uid))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {id} not found")
    await db.delete(agent)
    await db.commit()
    return {"status": "deleted"}


@router.post("/{name}/status", response_model=AgentResponse)
async def update_agent_status(
    name: str, body: AgentStatusUpdate, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    更新 Agent 状态。
    - status=running: 真正调用 LLM（执行 Agent 核心任务）
    - status=idle / error / offline: 只更新数据库
    """
    result = await db.execute(select(Agent).where(Agent.name == name))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {name} not found")

    new_status = body.status

    if new_status == "running":
        # ---- 真正调用 LLM ----
        # 构造 Agent 的系统提示词
        system_prompt = (
            f"You are {agent.name}, a {agent.role} agent. "
            f"{agent.description or ''}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Please introduce yourself as {agent.name} and describe your capabilities: {agent.capability_tags or 'general'}."},
        ]
        try:
            # 解析模型：bound 用指定模型，auto 则用 agent.model 作为偏好
            model = agent.model
            if agent.model_mode == "auto":
                # 自介场景用 role 匹配能力
                from app.runtime.model_router.router import default_router
                from app.runtime.model_router.models import ModelCapability
                role_caps = {
                    "architect": {ModelCapability.ARCHITECTURE_DESIGN, ModelCapability.REASONING},
                    "developer": {ModelCapability.CODE_GENERATION, ModelCapability.REASONING},
                    "tester": {ModelCapability.CODE_GENERATION, ModelCapability.FAST_RESPONSE},
                    "reviewer": {ModelCapability.CODE_GENERATION, ModelCapability.SUMMARIZATION},
                    "deployer": {ModelCapability.CODE_GENERATION, ModelCapability.TOOL_USE},
                }.get(agent.role, {ModelCapability.CODE_GENERATION})
                try:
                    decision = await default_router.route(
                        task_type=agent.role,
                        complexity=2,  # 自介是简单任务
                        required_capabilities=role_caps,
                    )
                    model = decision.model.name
                except Exception:
                    pass  # 路由失败用 agent.model 兜底

            # 调用 LLM（自动记录 LLMCall 到数据库）
            content, usage, _ = await llm_service.chat(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=1024,
                stream=False,
                db=db,           # 传入 db 以记录成本
                agent_id=str(agent.id),
                agent_name=agent.name,
                task_type="agent_intro",
            )
            # 更新 Agent 统计
            agent.status = "idle"
            agent.total_tasks = (agent.total_tasks or 0) + 1
            agent.completed_tasks = (agent.completed_tasks or 0) + 1
            if usage:
                agent.total_tokens = (agent.total_tokens or 0) + (usage.get("total_tokens") or 0)
                cost = (usage.get("prompt_tokens") or 0) / 1000 * 0.00015 + \
                       (usage.get("completion_tokens") or 0) / 1000 * 0.0006
                agent.total_cost = float(agent.total_cost or 0) + cost
            await db.commit()
        except Exception as e:
            agent.status = "error"
            agent.failed_tasks = (agent.failed_tasks or 0) + 1
            await db.commit()
            raise HTTPException(status_code=500, detail=f"LLM call failed: {e}") from e
    else:
        # 非 running 状态：只更新数据库
        agent.status = new_status
        await db.commit()

    await db.refresh(agent)
    return agent_to_dict(agent)
