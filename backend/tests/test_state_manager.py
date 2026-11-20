"""
W3 单元测试 — State Manager + Checkpoint Manager + State API
覆盖：State 生命周期 / Checkpoint 持久化 / 验证器 / API 端点
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.runtime.state_manager.lightweight_state import LightweightState
from app.runtime.state_manager.state_validator import StateValidator, StateTooLargeError
from app.runtime.state_manager.state_manager import StateManager
from app.runtime.checkpoint_manager.checkpoint_manager import CheckpointManager
from app.models.task import Task


@pytest_asyncio.fixture
async def task_with_state(db_session, sample_agent):
    uid = uuid.uuid4()
    task = Task(
        id=uid, name="State Test Task",
        goal_description="测试 State Manager",
        agent_id=uuid.UUID(sample_agent), agent_name="Test-Agent",
        status="pending", state_json={},
    )
    db_session.add(task)
    await db_session.commit()
    return str(uid)


@pytest_asyncio.fixture
async def state_mgr(db_session):
    return StateManager(db_session)


@pytest_asyncio.fixture
async def cp_mgr(db_session):
    return CheckpointManager(db_session, StateManager(db_session))


# ══════════════════════════════════════════
# LightweightState 数据结构（同步测试）
# ══════════════════════════════════════════

def test_create_for_task():
    state = LightweightState.create_for_task("task-123", "分析代码质量")
    assert state.task_id == "task-123"
    assert state.current_goal == "分析代码质量"
    assert state.workflow_status == "idle"


def test_add_message_truncates():
    state = LightweightState()
    for i in range(60):
        state.add_message("user", f"msg {i}")
    assert len(state.messages) == 50


def test_add_artifact_ref_dedup():
    state = LightweightState()
    state.add_artifact_ref("art-1")
    state.add_artifact_ref("art-1")
    assert len(state.artifact_refs) == 1


def test_to_dict_from_dict_roundtrip():
    original = LightweightState.create_for_task("t1", "goal")
    original.add_message("user", "hello")
    original.metadata = {"cost": 0.05}
    restored = LightweightState.from_dict(original.to_dict())
    assert restored.task_id == original.task_id


def test_from_dict_ignores_unknown_fields():
    state = LightweightState.from_dict({"task_id": "t1", "goo_field": "x"})
    assert state.task_id == "t1"


# ══════════════════════════════════════════
# StateValidator（同步测试）
# ══════════════════════════════════════════

def test_small_state_passes():
    warnings = StateValidator.validate(LightweightState.create_for_task("t1").to_dict())
    assert len(warnings) == 0


def test_size_limit_enforced():
    state = LightweightState.create_for_task("t1").to_dict()
    state["messages"] = [{"role": "user", "content": "x" * 100}] * 2000
    with pytest.raises(StateTooLargeError):
        StateValidator.validate(state)


def test_get_validator_size():
    size = StateValidator.get_size(LightweightState.create_for_task("t1").to_dict())
    assert size > 0


def test_warns_on_many_messages():
    state = LightweightState.create_for_task("t1").to_dict()
    state["messages"] = [{"role": "user", "content": "hi"}] * 120
    warnings = StateValidator.validate(state)
    assert any(w.field == "messages" for w in warnings)


# ══════════════════════════════════════════
# StateManager
# ══════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_initialize_and_load(state_mgr, task_with_state):
    state = await state_mgr.initialize(task_with_state, "goal")
    assert state.task_id == task_with_state
    loaded = await state_mgr.load(task_with_state)
    assert loaded is not None


@pytest.mark.asyncio
async def test_load_nonexistent(state_mgr):
    assert await state_mgr.load(str(uuid.uuid4())) is None


@pytest.mark.asyncio
async def test_save_and_update(state_mgr, task_with_state):
    state = await state_mgr.initialize(task_with_state)
    state.workflow_status = "running"
    state.current_node = "planner"
    await state_mgr.save(task_with_state, state)
    loaded = await state_mgr.load(task_with_state)
    assert loaded.workflow_status == "running"


@pytest.mark.asyncio
async def test_update_field(state_mgr, task_with_state):
    await state_mgr.initialize(task_with_state)
    updated = await state_mgr.update_field(task_with_state, {
        "workflow_status": "paused", "current_node": "reviewer",
    })
    assert updated.workflow_status == "paused"


@pytest.mark.asyncio
async def test_get_state_size(state_mgr, task_with_state):
    await state_mgr.initialize(task_with_state)
    assert await state_mgr.get_size(task_with_state) > 0


@pytest.mark.asyncio
async def test_cache_clearing(state_mgr, task_with_state):
    await state_mgr.initialize(task_with_state)
    state_mgr.clear_cache(task_with_state)
    assert await state_mgr.load(task_with_state) is not None


@pytest.mark.asyncio
async def test_size_limit_rejected(state_mgr, task_with_state):
    state = await state_mgr.initialize(task_with_state)
    state.messages = [{"role": "user", "content": "x" * 100}] * 2000
    with pytest.raises(StateTooLargeError):
        await state_mgr.save(task_with_state, state)


# ══════════════════════════════════════════
# CheckpointManager
# ══════════════════════════════════════════

@pytest.mark.asyncio
async def test_save_and_load_latest_cp(cp_mgr, state_mgr, task_with_state):
    await state_mgr.initialize(task_with_state, "goal")
    cp = await cp_mgr.save_checkpoint(task_with_state, event_seq_num=1)
    assert cp.task_id == uuid.UUID(task_with_state)
    latest = await cp_mgr.load_latest(task_with_state)
    assert latest is not None and latest.id == cp.id


@pytest.mark.asyncio
async def test_restore_from_checkpoint(cp_mgr, state_mgr, task_with_state):
    state = await state_mgr.initialize(task_with_state)
    state.workflow_status = "running"
    state.current_node = "executor"
    await state_mgr.save(task_with_state, state)
    cp = await cp_mgr.save_checkpoint(task_with_state)
    await state_mgr.update_field(task_with_state, {
        "workflow_status": "completed", "current_node": "done",
    })
    restored = await cp_mgr.restore_from_checkpoint(task_with_state, str(cp.id))
    assert restored.workflow_status == "running"


@pytest.mark.asyncio
async def test_restore_latest_cp(cp_mgr, state_mgr, task_with_state):
    await state_mgr.initialize(task_with_state)
    await cp_mgr.save_checkpoint(task_with_state)
    await state_mgr.update_field(task_with_state, {"workflow_status": "running"})
    # cp_mgr 的 StateManager 缓存了旧状态，需清除
    cp_mgr.state_manager.clear_cache(task_with_state)
    await cp_mgr.save_checkpoint(task_with_state)
    restored = await cp_mgr.restore_from_checkpoint(task_with_state)
    assert restored.workflow_status == "running"


@pytest.mark.asyncio
async def test_list_checkpoints(cp_mgr, state_mgr, task_with_state):
    await state_mgr.initialize(task_with_state)
    await cp_mgr.save_checkpoint(task_with_state)
    await cp_mgr.save_checkpoint(task_with_state)
    cps = await cp_mgr.list_checkpoints(task_with_state)
    assert len(cps) == 2


@pytest.mark.asyncio
async def test_delete_checkpoint(cp_mgr, state_mgr, task_with_state):
    await state_mgr.initialize(task_with_state)
    cp = await cp_mgr.save_checkpoint(task_with_state)
    assert await cp_mgr.delete_checkpoint(str(cp.id)) is True
    assert await cp_mgr.delete_checkpoint(str(cp.id)) is False


@pytest.mark.asyncio
async def test_no_checkpoint_for_nonexistent(cp_mgr):
    assert await cp_mgr.load_latest(str(uuid.uuid4())) is None


@pytest.mark.asyncio
async def test_prune_old_checkpoints(cp_mgr, state_mgr, task_with_state):
    await state_mgr.initialize(task_with_state)
    for i in range(25):
        await cp_mgr.save_checkpoint(task_with_state)
    cps = await cp_mgr.list_checkpoints(task_with_state)
    assert len(cps) <= 20


# ══════════════════════════════════════════
# State API 端点（client 来自 conftest，prefix=/api/v1）
# ══════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_get_state(client: AsyncClient, task_with_state):
    await client.post(f"/state/{task_with_state}/initialize")
    r = await client.get(f"/state/{task_with_state}")
    assert r.status_code == 200
    data = r.json()
    assert data["task_id"] == task_with_state
    assert "state" in data


@pytest.mark.asyncio
async def test_api_get_state_404(client: AsyncClient):
    r = await client.get(f"/state/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_initialize_state(client: AsyncClient, task_with_state):
    r = await client.post(f"/state/{task_with_state}/initialize?goal=test-goal")
    assert r.status_code == 200
    assert r.json()["initialized"] is True


@pytest.mark.asyncio
async def test_api_update_state(client: AsyncClient, task_with_state):
    await client.post(f"/state/{task_with_state}/initialize")
    r = await client.put(
        f"/state/{task_with_state}",
        json={"workflow_status": "running", "current_node": "planner"},
    )
    assert r.status_code == 200
    assert r.json()["state"]["workflow_status"] == "running"


@pytest.mark.asyncio
async def test_api_get_state_size(client: AsyncClient, task_with_state):
    await client.post(f"/state/{task_with_state}/initialize")
    r = await client.get(f"/state/{task_with_state}/size")
    assert r.status_code == 200
    assert "percent" in r.json()


@pytest.mark.asyncio
async def test_api_save_and_list_checkpoints(client: AsyncClient, task_with_state):
    await client.post(f"/state/{task_with_state}/initialize")
    await client.post(f"/state/{task_with_state}/checkpoints")
    r = await client.get(f"/state/{task_with_state}/checkpoints")
    assert r.status_code == 200
    assert r.json()["count"] >= 1


@pytest.mark.asyncio
async def test_api_get_latest_checkpoint(client: AsyncClient, task_with_state):
    await client.post(f"/state/{task_with_state}/initialize")
    await client.post(f"/state/{task_with_state}/checkpoints")
    r = await client.get(f"/state/{task_with_state}/checkpoints/latest")
    assert r.status_code == 200
    assert "state_snapshot" in r.json()


@pytest.mark.asyncio
async def test_api_restore_from_checkpoint(client: AsyncClient, task_with_state):
    await client.post(f"/state/{task_with_state}/initialize")
    await client.put(f"/state/{task_with_state}", json={"workflow_status": "running"})
    cp_id = (await client.post(f"/state/{task_with_state}/checkpoints")).json()["id"]
    await client.put(f"/state/{task_with_state}", json={"workflow_status": "completed"})
    r = await client.post(f"/state/{task_with_state}/checkpoints/{cp_id}/restore")
    assert r.status_code == 200
    assert r.json()["state"]["workflow_status"] == "running"


@pytest.mark.asyncio
async def test_api_delete_checkpoint(client: AsyncClient, task_with_state):
    await client.post(f"/state/{task_with_state}/initialize")
    cp_id = (await client.post(f"/state/{task_with_state}/checkpoints")).json()["id"]
    r = await client.delete(f"/state/{task_with_state}/checkpoints/{cp_id}")
    assert r.status_code == 200
