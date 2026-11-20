"""
Checkpoint Manager 测试 — W9
覆盖：save / load_latest / restore / list / delete / prune / 错误处理
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.runtime.checkpoint_manager import CheckpointManager
from app.runtime.state_manager.lightweight_state import LightweightState
from app.runtime.state_manager.state_manager import StateManager
from app.models.task import Task


# ── helpers ──

async def _create_task(db: AsyncSession, task_id: str | None = None) -> Task:
    """在测试 DB 中创建一个 Task 并返回"""
    tid = uuid.UUID(task_id) if task_id else uuid.uuid4()
    task = Task(
        id=tid,
        name=f"Test-{tid.hex[:6]}",
        status="running",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


def _make_state(task_id: str, node: str = "start", **kw) -> LightweightState:
    state = LightweightState.create_for_task(task_id)
    state.current_node = node
    state.workflow_status = "running"
    for k, v in kw.items():
        setattr(state, k, v)
    return state


# ── Test Class 1: Unit Tests ──

class TestCheckpointSave:
    """save_checkpoint 测试"""

    @pytest.mark.asyncio
    async def test_save_creates_checkpoint(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        # 先保存一个 State
        state = _make_state(tid, node="coding", error_count=0)
        await sm.save(tid, state)

        # 保存 Checkpoint
        cp = await cm.save_checkpoint(tid)

        assert cp is not None
        assert cp.id is not None
        assert str(cp.task_id) == tid
        assert cp.state_snapshot["current_node"] == "coding"
        assert cp.state_snapshot["task_id"] == tid

    @pytest.mark.asyncio
    async def test_save_auto_creates_state_if_missing(self, db_session: AsyncSession):
        """State 不存在时自动创建默认 State"""
        task = await _create_task(db_session)
        tid = str(task.id)
        cm = CheckpointManager(db_session)

        cp = await cm.save_checkpoint(tid)

        assert cp.state_snapshot["task_id"] == tid
        assert cp.state_snapshot["workflow_status"] == "idle"

    @pytest.mark.asyncio
    async def test_save_updates_task_last_checkpoint_id(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        cm = CheckpointManager(db_session)

        cp = await cm.save_checkpoint(tid)

        # 刷新 task 查看 last_checkpoint_id
        await db_session.refresh(task)
        assert task.last_checkpoint_id is not None
        assert task.last_checkpoint_id == cp.id

    @pytest.mark.asyncio
    async def test_save_preserves_event_seq_num(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        cm = CheckpointManager(db_session)

        cp = await cm.save_checkpoint(tid, event_seq_num=42)

        assert cp.event_seq_num == 42

    @pytest.mark.asyncio
    async def test_save_multiple_creates_distinct_entries(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        state1 = _make_state(tid, node="start")
        await sm.save(tid, state1)
        cp1 = await cm.save_checkpoint(tid)

        state2 = _make_state(tid, node="coding")
        await sm.save(tid, state2)
        cp2 = await cm.save_checkpoint(tid)

        assert cp1.id != cp2.id
        assert cp1.state_snapshot["current_node"] == "start"
        assert cp2.state_snapshot["current_node"] == "coding"

    @pytest.mark.asyncio
    async def test_save_updates_task_state_json(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        state = _make_state(tid, node="deploy", artifact_refs=["art-1"])
        await sm.save(tid, state)
        await cm.save_checkpoint(tid)

        await db_session.refresh(task)
        assert task.state_json["current_node"] == "deploy"
        assert "art-1" in task.state_json["artifact_refs"]


class TestCheckpointLoad:
    """load_latest 测试"""

    @pytest.mark.asyncio
    async def test_load_latest_returns_most_recent(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        s1 = _make_state(tid, node="one")
        await sm.save(tid, s1); await cm.save_checkpoint(tid)

        s2 = _make_state(tid, node="two")
        await sm.save(tid, s2); await cm.save_checkpoint(tid)

        latest = await cm.load_latest(tid)
        assert latest is not None
        assert latest.state_snapshot["current_node"] == "two"

    @pytest.mark.asyncio
    async def test_load_latest_no_checkpoints(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        cm = CheckpointManager(db_session)

        result = await cm.load_latest(tid)
        assert result is None


class TestCheckpointRestore:
    """restore_from_checkpoint 测试"""

    @pytest.mark.asyncio
    async def test_restore_latest(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        state = _make_state(tid, node="review", artifact_refs=["doc-1", "doc-2"])
        await sm.save(tid, state)
        await cm.save_checkpoint(tid)

        # 修改 state
        state.current_node = "overwritten"
        await sm.save(tid, state)

        # 恢复
        restored = await cm.restore_from_checkpoint(tid)
        assert restored.current_node == "review"
        assert restored.artifact_refs == ["doc-1", "doc-2"]

    @pytest.mark.asyncio
    async def test_restore_specific_checkpoint(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        s1 = _make_state(tid, node="first")
        await sm.save(tid, s1); cp1 = await cm.save_checkpoint(tid)

        s2 = _make_state(tid, node="second")
        await sm.save(tid, s2); await cm.save_checkpoint(tid)

        # 恢复到 cp1
        restored = await cm.restore_from_checkpoint(tid, str(cp1.id))
        assert restored.current_node == "first"

    @pytest.mark.asyncio
    async def test_restore_nonexistent_checkpoint_raises(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        cm = CheckpointManager(db_session)

        fake_id = str(uuid.uuid4())
        with pytest.raises(ValueError, match=f"Checkpoint {fake_id} not found"):
            await cm.restore_from_checkpoint(tid, fake_id)

    @pytest.mark.asyncio
    async def test_restore_no_checkpoint_raises(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        cm = CheckpointManager(db_session)

        with pytest.raises(ValueError, match=f"No checkpoint found for task {tid}"):
            await cm.restore_from_checkpoint(tid)


class TestCheckpointList:
    """list_checkpoints 测试"""

    @pytest.mark.asyncio
    async def test_list_returns_all_in_reverse_order(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        for i in range(3):
            s = _make_state(tid, node=f"step{i}")
            await sm.save(tid, s)
            await cm.save_checkpoint(tid, event_seq_num=i)

        cps = await cm.list_checkpoints(tid)
        assert len(cps) == 3
        # 最新在前
        assert cps[0]["node"] == "step2"
        assert cps[1]["node"] == "step1"
        assert cps[2]["node"] == "step0"

    @pytest.mark.asyncio
    async def test_list_no_checkpoints(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        cm = CheckpointManager(db_session)

        cps = await cm.list_checkpoints(tid)
        assert cps == []

    @pytest.mark.asyncio
    async def test_list_contains_required_fields(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        s = _make_state(tid, node="deploy")
        s.workflow_status = "running"
        await sm.save(tid, s)
        await cm.save_checkpoint(tid, event_seq_num=10)

        cps = await cm.list_checkpoints(tid)
        entry = cps[0]
        assert "id" in entry
        assert "task_id" in entry
        assert "created_at" in entry
        assert "event_seq_num" in entry
        assert "node" in entry
        assert "workflow_status" in entry
        assert "state_size" in entry
        assert entry["event_seq_num"] == 10


class TestCheckpointDelete:
    """delete_checkpoint 测试"""

    @pytest.mark.asyncio
    async def test_delete_existing(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        s = _make_state(tid, node="step")
        await sm.save(tid, s)
        cp = await cm.save_checkpoint(tid)

        result = await cm.delete_checkpoint(str(cp.id))
        assert result is True

        cps = await cm.list_checkpoints(tid)
        assert len(cps) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, db_session: AsyncSession):
        cm = CheckpointManager(db_session)
        result = await cm.delete_checkpoint(str(uuid.uuid4()))
        assert result is False


class TestCheckpointPrune:
    """自动清理旧 Checkpoint 测试"""

    @pytest.mark.asyncio
    async def test_prune_excess(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        # 创建 25 个（超过 MAX=20）
        for i in range(25):
            s = _make_state(tid, node=f"step{i}")
            await sm.save(tid, s)
            await cm.save_checkpoint(tid, event_seq_num=i)

        cps = await cm.list_checkpoints(tid)
        assert len(cps) == 20  # 只保留 20 个

        # 最新 20 个保留（step24..step5），最旧 5 个被清理
        nodes = [cp["node"] for cp in cps]
        assert "step24" in nodes  # 最新的保留
        assert "step0" not in nodes  # 最旧的被清理

    @pytest.mark.asyncio
    async def test_prune_no_excess(self, db_session: AsyncSession):
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        for i in range(5):
            s = _make_state(tid, node=f"step{i}")
            await sm.save(tid, s)
            await cm.save_checkpoint(tid)

        cps = await cm.list_checkpoints(tid)
        assert len(cps) == 5  # 全部保留


# ── Test Class 2: Integration ──

class TestCheckpointIntegration:
    """Checkpoint + StateManager 集成测试"""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, db_session: AsyncSession):
        """完整的 checkpoint 生命周期"""
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        # 1. 执行 step1
        s1 = _make_state(tid, node="init", steps=[{"node": "init", "outcome": "ok"}])
        await sm.save(tid, s1)
        cp1 = await cm.save_checkpoint(tid, event_seq_num=1)

        # 2. 执行 step2
        s2 = _make_state(tid, node="code_gen", steps=[{"node": "code_gen", "outcome": "ok"}])
        s2.artifact_refs = ["file.py"]
        await sm.save(tid, s2)
        cp2 = await cm.save_checkpoint(tid, event_seq_num=2)

        # 3. 列出 checkpoint
        cps = await cm.list_checkpoints(tid)
        assert len(cps) == 2

        # 4. 恢复
        restored = await cm.restore_from_checkpoint(tid, str(cp1.id))
        assert restored.current_node == "init"

        # 5. 删除
        assert await cm.delete_checkpoint(str(cp2.id)) is True
        cps = await cm.list_checkpoints(tid)
        assert len(cps) == 1

    @pytest.mark.asyncio
    async def test_concurrent_checkpoints(self, db_session: AsyncSession):
        """同一 task 连续保存多个 checkpoint（模拟节点间自动保存）"""
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        nodes = ["start", "validate", "execute", "verify", "complete"]
        for i, node in enumerate(nodes):
            s = _make_state(tid, node=node, error_count=0)
            await sm.save(tid, s)
            await cm.save_checkpoint(tid, event_seq_num=i)

        cps = await cm.list_checkpoints(tid)
        assert len(cps) == 5
        assert cps[0]["node"] == "complete"  # latest first

    @pytest.mark.asyncio
    async def test_restore_preserves_all_state_fields(self, db_session: AsyncSession):
        """恢复后所有 State 字段完整保留"""
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        original = LightweightState(
            task_id=tid,
            project_id="proj-1",
            current_node="code_review",
            workflow_status="running",
            error_count=2,
            max_retries=5,
            artifact_refs=["art-a", "art-b"],
            context_refs=["ctx-1"],
            approval_needed=True,
            approval_result=None,
            messages=[{"role": "user", "content": "review this"}],
            current_goal="Fix all bugs",
            metadata={"priority": "high"},
            steps=[
                {"node": "start", "outcome": "ok"},
                {"node": "coding", "outcome": "partial"},
            ],
        )
        await sm.save(tid, original)
        cp = await cm.save_checkpoint(tid)

        # 修改原 state（模拟继续执行）
        original.current_node = "deploy"
        original.error_count = 99
        await sm.save(tid, original)

        # 恢复
        restored = await cm.restore_from_checkpoint(tid, str(cp.id))

        assert restored.task_id == tid
        assert restored.project_id == "proj-1"
        assert restored.current_node == "code_review"
        assert restored.workflow_status == "running"
        assert restored.error_count == 2
        assert restored.max_retries == 5
        assert restored.artifact_refs == ["art-a", "art-b"]
        assert restored.context_refs == ["ctx-1"]
        assert restored.approval_needed is True
        assert restored.messages == [{"role": "user", "content": "review this"}]
        assert restored.current_goal == "Fix all bugs"
        assert restored.metadata == {"priority": "high"}
        assert len(restored.steps) == 2

    @pytest.mark.asyncio
    async def test_prune_keeps_latest_checkpoints(self, db_session: AsyncSession):
        """超量清理后最新 20 个保留且正确"""
        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        cp_ids = []
        for i in range(30):
            s = _make_state(tid, node=f"step_{i:02d}")
            await sm.save(tid, s)
            cp = await cm.save_checkpoint(tid, event_seq_num=i)
            cp_ids.append(str(cp.id))

        cps = await cm.list_checkpoints(tid)
        assert len(cps) == 20

        # 最早的 10 个被清理
        for i in range(10):
            assert await cm.delete_checkpoint(cp_ids[i]) is False

        # 最新的 20 个还在
        for i in range(20, 30):
            assert await cm.delete_checkpoint(cp_ids[i]) is True


# ── Test Class 3: LangGraphAdapter + CheckpointManager ──

class TestAdapterCheckpointIntegration:
    """LangGraphAdapter 执行时自动保存 Checkpoint"""

    @pytest.mark.asyncio
    async def test_astream_saves_checkpoint_per_node(self, db_session: AsyncSession):
        """astream 执行时每个节点后自动写 checkpoint"""
        from unittest.mock import AsyncMock
        from app.runtime.execution_engine.langgraph_adapter import LangGraphAdapter
        from app.runtime.execution_engine.workflow_schema import (
            WorkflowSpec, NodeSpec, EdgeSpec, NodeType, create_default_state,
        )
        from app.runtime.execution_engine.node_executor import NodeExecutor

        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        # Mock tool executor
        mock_tool = AsyncMock()
        mock_tool.execute.return_value = {"result": "ok"}

        executor = NodeExecutor(tool_executor=mock_tool)
        adapter = LangGraphAdapter(
            node_executor=executor,
            checkpoint_manager=cm,
        )

        # 构建简单 workflow: start → tool → end
        spec = WorkflowSpec(
            name="checkpoint_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="run_tool", type=NodeType.TOOL, config={
                    "tool_name": "mock_tool", "inputs": {},
                }),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="run_tool"),
                EdgeSpec(source="run_tool", target="end"),
            ],
        )

        graph = adapter.build(spec)
        state = create_default_state(task_id=tid)

        async for _ in adapter.astream(graph, state, tid):
            pass

        # 验证 checkpoint 已保存
        cps = await cm.list_checkpoints(tid)
        assert len(cps) >= 2  # start + run_tool 各至少一个

    @pytest.mark.asyncio
    async def test_astream_without_checkpoint_mgr_still_works(self):
        """没有 CheckpointManager 时 astream 正常运行（不崩溃）"""
        from unittest.mock import AsyncMock
        from app.runtime.execution_engine.langgraph_adapter import LangGraphAdapter
        from app.runtime.execution_engine.workflow_schema import (
            WorkflowSpec, NodeSpec, EdgeSpec, NodeType, create_default_state,
        )
        from app.runtime.execution_engine.node_executor import NodeExecutor

        mock_tool = AsyncMock()
        mock_tool.execute.return_value = {"result": "ok"}

        adapter = LangGraphAdapter(
            node_executor=NodeExecutor(tool_executor=mock_tool),
            checkpoint_manager=None,  # 无 checkpoint
        )

        spec = WorkflowSpec(
            name="no_cp_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="run_tool", type=NodeType.TOOL, config={
                    "tool_name": "mock_tool", "inputs": {},
                }),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="run_tool"),
                EdgeSpec(source="run_tool", target="end"),
            ],
        )

        graph = adapter.build(spec)
        state = create_default_state(task_id="no-cp-1")

        events = []
        async for evt in adapter.astream(graph, state, "no-cp-1"):
            events.append(evt)

        assert any(e["event"] == "completed" for e in events)

    @pytest.mark.asyncio
    async def test_checkpoint_after_error(self, db_session: AsyncSession):
        """错误发生后仍有 checkpoint（故障恢复基础）"""
        from app.runtime.execution_engine.langgraph_adapter import LangGraphAdapter
        from app.runtime.execution_engine.workflow_schema import (
            WorkflowSpec, NodeSpec, EdgeSpec, NodeType, create_default_state,
        )
        from app.runtime.execution_engine.node_executor import NodeExecutor

        task = await _create_task(db_session)
        tid = str(task.id)
        sm = StateManager(db_session)
        cm = CheckpointManager(db_session, sm)

        # 使用真实 executor（无注册 tool → 会报错但不崩溃）
        adapter = LangGraphAdapter(
            node_executor=NodeExecutor(),
            checkpoint_manager=cm,
        )

        spec = WorkflowSpec(
            name="error_cp_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="fail_tool", type=NodeType.TOOL, config={
                    "tool_name": "nonexistent", "inputs": {},
                }),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="fail_tool"),
                EdgeSpec(source="fail_tool", target="end"),
            ],
        )

        graph = adapter.build(spec)
        state = create_default_state(task_id=tid)

        events = []
        async for evt in adapter.astream(graph, state, tid):
            events.append(evt)

        # 即使有错误，也应该完成（error_count 递增）
        # 验证至少保存了 start 节点的 checkpoint
        cps = await cm.list_checkpoints(tid)
        # start 节点执行后至少应该有一个 checkpoint
        assert len(cps) >= 1
