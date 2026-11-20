"""
Agent 执行引擎 E2E 测试
覆盖：execute / cancel / 状态校验 / 并发控制 / 生命周期
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task


@pytest.mark.asyncio
async def test_execute_task_marks_running(client: AsyncClient, sample_agent: str, db_session: AsyncSession):
    """execute 端点将任务标记为 running 并返回 started"""
    r = await client.post("/tasks", json={
        "name": "Execute Mark Running",
        "agent_id": sample_agent,
        "priority": "high",
    })
    assert r.status_code == 201
    tid = r.json()["id"]

    r = await client.post(f"/tasks/{tid}/execute")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "started"
    assert data["task_id"] == tid

    # 验证 DB 中 status 已更新为 running
    await db_session.refresh(await db_session.get(Task, uuid.UUID(tid)))
    # 用原生查询避开 ORM 缓存
    result = await db_session.execute(
        select(Task.status).where(Task.id == uuid.UUID(tid))
    )
    status = result.scalar_one()
    assert status == "running"


@pytest.mark.asyncio
async def test_execute_task_no_agent(client: AsyncClient):
    """无 Agent 分配时拒绝执行"""
    r = await client.post("/tasks", json={"name": "No Agent Task"})
    tid = r.json()["id"]

    r = await client.post(f"/tasks/{tid}/execute")
    assert r.status_code == 400
    assert "no assigned agent" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_execute_task_not_found(client: AsyncClient):
    """执行不存在的任务返回 404"""
    r = await client.post("/tasks/00000000-0000-0000-0000-000000000001/execute")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_execute_already_running_task(client: AsyncClient, sample_agent: str, db_session: AsyncSession):
    """不允许重复执行正在 running 的任务 — 返回 409"""
    r = await client.post("/tasks", json={
        "name": "Already Running",
        "agent_id": sample_agent,
    })
    tid = r.json()["id"]

    # 第一次执行 — 标记为 running
    await client.post(f"/tasks/{tid}/execute")

    # 第二次执行应被拒绝
    r2 = await client.post(f"/tasks/{tid}/execute")
    assert r2.status_code == 409
    assert "already" in r2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_execute_completed_task(client: AsyncClient, sample_agent: str, db_session: AsyncSession):
    """已完成的任务不能再次执行"""
    r = await client.post("/tasks", json={
        "name": "Completed Task",
        "agent_id": sample_agent,
    })
    tid = r.json()["id"]

    # 手动标记为 completed
    task = await db_session.get(Task, uuid.UUID(tid))
    task.status = "completed"
    await db_session.commit()

    r = await client.post(f"/tasks/{tid}/execute")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_cancel_task(client: AsyncClient, sample_agent: str, db_session: AsyncSession):
    """取消正在 running 的任务"""
    r = await client.post("/tasks", json={
        "name": "Cancel Me",
        "agent_id": sample_agent,
    })
    tid = r.json()["id"]

    # 先标记为 running（模拟执行状态）
    task = await db_session.get(Task, uuid.UUID(tid))
    task.status = "running"
    await db_session.commit()

    # 取消
    r = await client.post(f"/tasks/{tid}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    # 验证 DB
    await db_session.refresh(task)
    assert task.status == "cancelled"
    assert task.completed_at is not None


@pytest.mark.asyncio
async def test_cancel_non_running_task(client: AsyncClient, sample_agent: str):
    """不能取消未在运行的任务"""
    r = await client.post("/tasks", json={
        "name": "Not Running",
        "agent_id": sample_agent,
    })
    tid = r.json()["id"]

    r = await client.post(f"/tasks/{tid}/cancel")
    assert r.status_code == 409
    assert "not running" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_executions(client: AsyncClient):
    """列出活跃执行"""
    r = await client.get("/tasks/executions")
    assert r.status_code == 200
    data = r.json()
    assert "active_count" in data
    assert "max_concurrent" in data
    assert data["max_concurrent"] == 5
    assert isinstance(data["task_ids"], list)


@pytest.mark.asyncio
async def test_kanban_task_flow(client: AsyncClient, sample_agent: str, db_session: AsyncSession):
    """完整 Kanban 流程：创建 → 手动状态变更 → 验证看板列"""
    # 1. 创建任务 → todo 列
    r = await client.post("/tasks", json={
        "name": "Kanban Flow Test",
        "agent_id": sample_agent,
    })
    tid = r.json()["id"]

    r = await client.get("/tasks/kanban")
    cols = r.json()
    todo = next(c for c in cols if c["type"] == "todo")
    assert any(t["id"] == tid for t in todo["tasks"])

    # 2. 移入 in_progress
    await client.put(f"/tasks/{tid}", json={"kanban_column": "in_progress"})
    r = await client.get("/tasks/kanban")
    cols = r.json()
    ip = next(c for c in cols if c["type"] == "in_progress")
    assert any(t["id"] == tid for t in ip["tasks"])

    # 3. 移入 done
    await client.put(f"/tasks/{tid}", json={"kanban_column": "done"})
    r = await client.get("/tasks/kanban")
    cols = r.json()
    done = next(c for c in cols if c["type"] == "done")
    assert any(t["id"] == tid for t in done["tasks"])

    # 4. 移入 failed
    await client.put(f"/tasks/{tid}", json={"kanban_column": "failed"})
    r = await client.get("/tasks/kanban")
    cols = r.json()
    failed = next(c for c in cols if c["type"] == "failed")
    assert any(t["id"] == tid for t in failed["tasks"])


@pytest.mark.asyncio
async def test_kanban_column_normalization(client: AsyncClient, sample_agent: str, db_session: AsyncSession):
    """Kanban 列名规范化：backlog/ready/pending → todo"""
    r = await client.post("/tasks", json={
        "name": "Backlog Task",
        "agent_id": sample_agent,
    })
    tid = r.json()["id"]

    # 设置 kanban_column 为 backlog
    task = await db_session.get(Task, uuid.UUID(tid))
    task.kanban_column = "backlog"
    await db_session.commit()

    # kanban 看板应映射到 todo 列
    r = await client.get("/tasks/kanban")
    cols = r.json()
    todo = next(c for c in cols if c["type"] == "todo")
    assert any(t["id"] == tid for t in todo["tasks"])

    # running → in_progress
    task.kanban_column = "running"
    await db_session.commit()
    r = await client.get("/tasks/kanban")
    cols = r.json()
    ip = next(c for c in cols if c["type"] == "in_progress")
    assert any(t["id"] == tid for t in ip["tasks"])
