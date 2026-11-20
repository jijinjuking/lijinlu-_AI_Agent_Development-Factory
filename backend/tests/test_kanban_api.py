"""
Kanban API 测试
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_task(client: AsyncClient, sample_agent: str):
    """创建任务"""
    r = await client.post("/tasks", json={
        "name": "Test Task",
        "goal_description": "Test description",
        "agent_id": sample_agent,
        "priority": "high",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "Test Task"
    assert data["kanban_column"] == "todo"
    assert data["priority"] == "high"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_tasks(client: AsyncClient, sample_agent: str):
    """列出任务"""
    # Create 3 tasks
    for i in range(3):
        await client.post("/tasks", json={
            "name": f"Task {i}",
            "agent_id": sample_agent,
        })
    r = await client.get("/tasks")
    assert r.status_code == 200
    tasks = r.json()
    assert len(tasks) == 3


@pytest.mark.asyncio
async def test_kanban_board_empty(client: AsyncClient):
    """看板无数据时返回 5 空列"""
    r = await client.get("/tasks/kanban")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 5
    expected_types = {"todo", "in_progress", "review", "done", "failed"}
    actual_types = {col["type"] for col in data}
    assert actual_types == expected_types


@pytest.mark.asyncio
async def test_kanban_board_with_tasks(client: AsyncClient, sample_agent: str):
    """看板有任务时正确分配列"""
    await client.post("/tasks", json={"name": "Todo Task", "agent_id": sample_agent})
    r = await client.get("/tasks/kanban")
    assert r.status_code == 200
    data = r.json()
    todo_col = next(c for c in data if c["type"] == "todo")
    assert len(todo_col["tasks"]) == 1


@pytest.mark.asyncio
async def test_update_task(client: AsyncClient, sample_agent: str):
    """更新任务状态"""
    r = await client.post("/tasks", json={"name": "Update Test", "agent_id": sample_agent})
    tid = r.json()["id"]

    r = await client.put(f"/tasks/{tid}", json={"kanban_column": "in_progress"})
    assert r.status_code == 200
    assert r.json()["kanban_column"] == "in_progress"


@pytest.mark.asyncio
async def test_delete_task(client: AsyncClient, sample_agent: str):
    """删除任务"""
    r = await client.post("/tasks", json={"name": "Delete Me", "agent_id": sample_agent})
    tid = r.json()["id"]

    r = await client.delete(f"/tasks/{tid}")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"

    r = await client.get(f"/tasks/{tid}")
    assert r.status_code == 404
