"""
W19 Recovery Manager — 单元测试

测试范围:
- models.py        (Recovery models / enums)
- failure_detector.py (FailureDetector)
- state_rollback.py  (StateRollback)
- auto_recovery.py    (RecoveryOrchestrator)

使用 mock 注入 checkpoint_manager / state_manager。
"""

import time
from dataclasses import dataclass
from typing import Any, Optional

import pytest

from app.runtime.recovery_manager.models import (
    FailureType,
    RecoveryAction,
    RecoveryStatus,
    FailureEvent,
    RecoveryPlan,
    RecoveryResult,
)
from app.runtime.recovery_manager.failure_detector import (
    FailureDetector,
    DetectorConfig,
)
from app.runtime.recovery_manager.state_rollback import StateRollback
from app.runtime.recovery_manager.auto_recovery import RecoveryOrchestrator


# ============================================================================
# Mocks
# ============================================================================

@dataclass
class MockCheckpoint:
    state_snapshot: Any
    event_seq_num: int = 0


class MockCheckpointManager:
    def __init__(self):
        self.checkpoints = {}

    async def save_checkpoint(self, task_id, state_snapshot, **kw):
        self.checkpoints[task_id] = state_snapshot

    async def load_latest(self, task_id):
        snap = self.checkpoints.get(task_id)
        return MockCheckpoint(snap) if snap else None


class MockStateManager:
    def __init__(self):
        self.states = {}

    async def initialize(self, task_id, goal):
        self.states[task_id] = {"goal": goal, "messages": [], "artifact_refs": []}

    async def load(self, task_id):
        return self.states.get(task_id, {})

    async def save(self, task_id, state):
        self.states[task_id] = state

    async def update_field(self, task_id, fields):
        s = self.states.setdefault(task_id, {})
        s.update(fields)


# ============================================================================
# 1. Models Tests (12 cases)
# ============================================================================
class TestFailureType:
    def test_all_members(self):
        assert FailureType.TIMEOUT.value == "timeout"
        assert FailureType.CRASH.value == "crash"
        assert FailureType.OOM.value == "oom"
        assert FailureType.NETWORK.value == "network"
        assert FailureType.SANDBOX_FAILURE.value == "sandbox_failure"
        assert FailureType.UNKNOWN.value == "unknown"

    def test_from_string(self):
        assert FailureType("timeout") == FailureType.TIMEOUT
        with pytest.raises(ValueError):
            FailureType("nonexistent")


class TestRecoveryAction:
    def test_all_members(self):
        assert RecoveryAction.RETRY.value == "retry"
        assert RecoveryAction.ROLLBACK.value == "rollback"
        assert RecoveryAction.FAILOVER.value == "failover"
        assert RecoveryAction.SKIP.value == "skip"
        assert RecoveryAction.HUMAN_INTERVENTION.value == "human_intervention"


class TestRecoveryStatus:
    def test_all_members(self):
        assert RecoveryStatus.PENDING.value == "pending"
        assert RecoveryStatus.IN_PROGRESS.value == "in_progress"
        assert RecoveryStatus.SUCCESS.value == "success"
        assert RecoveryStatus.FAILED.value == "failed"


class TestFailureEvent:
    def test_defaults(self):
        evt = FailureEvent(task_id="t1", failure_type=FailureType.TIMEOUT, message="test")
        assert evt.task_id == "t1"
        assert isinstance(evt.timestamp, float)
        assert evt.checkpoint_seq_num == 0
        assert evt.metadata == {}

    def test_custom_fields(self):
        evt = FailureEvent(
            task_id="t2", failure_type=FailureType.CRASH, message="crash",
            node_id="n1", checkpoint_seq_num=5, metadata={"env": "prod"},
        )
        assert evt.node_id == "n1"
        assert evt.checkpoint_seq_num == 5
        assert evt.metadata["env"] == "prod"


class TestRecoveryPlan:
    def test_current_action(self):
        plan = RecoveryPlan(
            task_id="t1", failure_type=FailureType.TIMEOUT,
            actions=[RecoveryAction.RETRY, RecoveryAction.HUMAN_INTERVENTION],
        )
        assert plan.current_action == RecoveryAction.RETRY

    def test_current_action_empty(self):
        plan = RecoveryPlan(task_id="t1", failure_type=FailureType.TIMEOUT, actions=[])
        assert plan.current_action is None

    def test_advance(self):
        plan = RecoveryPlan(
            task_id="t1", failure_type=FailureType.TIMEOUT,
            actions=[RecoveryAction.RETRY, RecoveryAction.ROLLBACK, RecoveryAction.HUMAN_INTERVENTION],
        )
        assert plan.current_action == RecoveryAction.RETRY
        assert plan.advance() == RecoveryAction.ROLLBACK
        assert plan.current_action_index == 1
        assert plan.advance() == RecoveryAction.HUMAN_INTERVENTION
        assert plan.advance() is None

    def test_advance_empty(self):
        plan = RecoveryPlan(task_id="t1", failure_type=FailureType.TIMEOUT, actions=[])
        assert plan.advance() is None

    def test_status_transitions(self):
        plan = RecoveryPlan(
            task_id="t1", failure_type=FailureType.TIMEOUT,
            actions=[RecoveryAction.RETRY],
        )
        assert plan.status == RecoveryStatus.PENDING
        plan.status = RecoveryStatus.IN_PROGRESS
        assert plan.status == RecoveryStatus.IN_PROGRESS
        plan.status = RecoveryStatus.SUCCESS
        assert plan.status == RecoveryStatus.SUCCESS


class TestRecoveryResult:
    def test_success(self):
        r = RecoveryResult(task_id="t1", success=True)
        assert r.success
        assert r.actions_taken == []
        assert r.failure_reason is None

    def test_failure_with_reason(self):
        r = RecoveryResult(
            task_id="t1", success=False, failure_reason="OOM",
            actions_taken=[RecoveryAction.RETRY], recovered_checkpoint=3, duration_seconds=1.5,
        )
        assert not r.success
        assert r.failure_reason == "OOM"
        assert r.recovered_checkpoint == 3
        assert r.duration_seconds == 1.5


# ============================================================================
# 2. FailureDetector Tests (15 cases)
# ============================================================================
class TestFailureDetectorModels:
    def test_detector_config_defaults(self):
        cfg = DetectorConfig()
        assert cfg.heartbeat_timeout_seconds == 30.0
        assert cfg.max_consecutive_failures == 3
        assert cfg.oom_memory_threshold_mb == 2048
        assert cfg.check_interval_seconds == 5.0

    def test_detector_config_custom(self):
        cfg = DetectorConfig(heartbeat_timeout_seconds=10.0, max_consecutive_failures=5)
        assert cfg.heartbeat_timeout_seconds == 10.0
        assert cfg.max_consecutive_failures == 5


class TestFailureDetectorHeartbeat:
    def test_heartbeat_registers(self):
        d = FailureDetector()
        d.heartbeat("t1")
        hb = d._heartbeats["t1"]
        assert hb.task_id == "t1"
        assert hb.consecutive_misses == 0

    def test_heartbeat_resets_misses(self):
        d = FailureDetector()
        d.heartbeat("t1")
        d._heartbeats["t1"].consecutive_misses = 2
        d.heartbeat("t1")
        assert d._heartbeats["t1"].consecutive_misses == 0

    def test_check_heartbeat_no_heartbeat(self):
        d = FailureDetector()
        assert d.check_heartbeat("nonexistent") is None

    def test_check_heartbeat_within_timeout(self):
        d = FailureDetector(DetectorConfig(heartbeat_timeout_seconds=30.0))
        d.heartbeat("t1")
        assert d.check_heartbeat("t1") is None

    def test_check_heartbeat_timeout_accumulates(self):
        d = FailureDetector(DetectorConfig(heartbeat_timeout_seconds=0.01, max_consecutive_failures=5))
        d.heartbeat("t1")
        time.sleep(0.02)
        result = d.check_heartbeat("t1")
        assert result is None  # only 1 miss, need 3
        assert d._heartbeats["t1"].consecutive_misses == 1

    def test_check_heartbeat_triggers_failure(self):
        d = FailureDetector(DetectorConfig(heartbeat_timeout_seconds=0.01, max_consecutive_failures=1))
        d.heartbeat("t1")
        time.sleep(0.02)
        result = d.check_heartbeat("t1")
        assert result is not None
        assert result.failure_type == FailureType.TIMEOUT


class TestFailureDetectorDetectMethods:
    def test_detect_crash(self):
        d = FailureDetector()
        evt = d.detect_crash("t1", RuntimeError("segfault"))
        assert evt.task_id == "t1"
        assert evt.failure_type == FailureType.CRASH
        assert "segfault" in evt.message

    def test_detect_oom_exceeds(self):
        d = FailureDetector()
        evt = d.detect_oom("t1", 4096)
        assert evt is not None
        assert evt.failure_type == FailureType.OOM

    def test_detect_oom_within_limit(self):
        d = FailureDetector()
        assert d.detect_oom("t1", 1024) is None

    def test_detect_sandbox_failure(self):
        d = FailureDetector()
        evt = d.detect_sandbox_failure("t1", "sandbox crashed")
        assert evt.failure_type == FailureType.SANDBOX_FAILURE

    def test_detect_network_failure(self):
        d = FailureDetector()
        evt = d.detect_network_failure("t1", "connection refused")
        assert evt.failure_type == FailureType.NETWORK


class TestFailureDetectorPlanAndHistory:
    def test_create_recovery_plan_timeout(self):
        d = FailureDetector()
        failure = d.detect_crash("t1", Exception("boom"))
        plan = d.create_recovery_plan(failure)
        assert plan.failure_type == FailureType.CRASH
        assert RecoveryAction.ROLLBACK in plan.actions
        assert RecoveryAction.RETRY in plan.actions

    def test_create_recovery_plan_oom(self):
        d = FailureDetector()
        failure = d.detect_oom("t1", 4096)
        assert failure is not None
        plan = d.create_recovery_plan(failure)
        assert RecoveryAction.RETRY in plan.actions
        assert RecoveryAction.ROLLBACK not in plan.actions

    def test_get_history_empty(self):
        d = FailureDetector()
        assert d.get_history("t1") == []

    def test_get_history_after_failure(self):
        d = FailureDetector()
        d.detect_crash("t1", Exception("e1"))
        d.detect_crash("t1", Exception("e2"))
        assert len(d.get_history("t1")) == 2

    def test_clear_history(self):
        d = FailureDetector()
        d.detect_crash("t1", Exception("e"))
        d.clear_history("t1")
        assert d.get_history("t1") == []
        assert "t1" not in d._heartbeats


class TestFailureDetectorHandlers:
    def test_on_failure_and_handle(self):
        d = FailureDetector()
        results = []
        d.on_failure(FailureType.CRASH, lambda evt: results.append(str(evt)))
        evt = d.detect_crash("t1", Exception("test"))
        # handle_failure is async but uses asyncio.iscoroutinefunction internally
        import asyncio
        asyncio.run(d.handle_failure(evt))
        assert len(results) == 1

    def test_on_failure_async_handler(self):
        d = FailureDetector()
        results = []
        async def async_handler(evt):
            results.append("async:" + evt.task_id)
        d.on_failure(FailureType.CRASH, async_handler)
        evt = d.detect_crash("t1", Exception("test"))
        import asyncio
        asyncio.run(d.handle_failure(evt))
        assert len(results) == 1
        assert "async" in results[0]

    def test_handler_exception_does_not_block_others(self):
        d = FailureDetector()
        results = []
        def bad_handler(evt):
            raise RuntimeError("handler error")
        def good_handler(evt):
            results.append("ok")
        d.on_failure(FailureType.CRASH, bad_handler)
        d.on_failure(FailureType.CRASH, good_handler)
        evt = d.detect_crash("t1", Exception("test"))
        import asyncio
        asyncio.run(d.handle_failure(evt))
        assert "ok" in results


# ============================================================================
# 3. StateRollback Tests (10 cases)
# ============================================================================
class TestStateRollback:
    @pytest.fixture
    def rb_setup(self):
        cp = MockCheckpointManager()
        sm = MockStateManager()
        rb = StateRollback(cp, sm)
        return cp, sm, rb

    @pytest.mark.asyncio
    async def test_rollback_full_success(self, rb_setup):
        cp, sm, rb = rb_setup
        task_id = "t-rollback-full"
        await sm.initialize(task_id, "test goal")
        await cp.save_checkpoint(task_id, {"goal": "test goal", "phase": "executing"})
        result = await rb.rollback(
            task_id, FailureEvent(task_id, FailureType.CRASH, "test"), method="full"
        )
        assert result.success
        state = await sm.load(task_id)
        assert state["phase"] == "executing"

    @pytest.mark.asyncio
    async def test_rollback_no_checkpoint(self, rb_setup):
        cp, sm, rb = rb_setup
        task_id = "t-no-ckpt"
        result = await rb.rollback(
            task_id, FailureEvent(task_id, FailureType.CRASH, "test"), method="full"
        )
        assert not result.success
        failure = (result.failure_reason or "").lower()
        assert "checkpoint" in failure

    @pytest.mark.asyncio
    async def test_rollback_partial(self, rb_setup):
        cp, sm, rb = rb_setup
        task_id = "t-partial"
        await sm.initialize(task_id, "goal")
        await sm.save(task_id, {"goal": "goal", "phase": "old", "messages": ["m1"], "artifact_refs": ["a1"]})
        await cp.save_checkpoint(task_id, {"goal": "goal", "phase": "recovered"})
        result = await rb.rollback(
            task_id, FailureEvent(task_id, FailureType.CRASH, "test"), method="partial"
        )
        assert result.success
        state = await sm.load(task_id)
        assert "messages" in state

    @pytest.mark.asyncio
    async def test_rollback_replay_returns_empty(self, rb_setup):
        cp, sm, rb = rb_setup
        task_id = "t-replay"
        await sm.initialize(task_id, "goal")
        await cp.save_checkpoint(task_id, {"goal": "goal", "phase": "ckpt"})
        result = await rb.rollback(
            task_id, FailureEvent(task_id, FailureType.CRASH, "test"), method="replay"
        )
        # replay events is empty (placeholder), so this is essentially a no-op
        assert isinstance(result, RecoveryResult)

    @pytest.mark.asyncio
    async def test_rollback_unknown_method(self, rb_setup):
        cp, sm, rb = rb_setup
        result = await rb.rollback(
            "t-unknown", FailureEvent("t-unknown", FailureType.CRASH, "test"), method="nonexistent"
        )
        assert not result.success

    def test_get_rollback_history(self, rb_setup):
        cp, sm, rb = rb_setup
        hist = rb.get_rollback_history("t-hist")
        assert isinstance(hist, list)

    def test_apply_event_artifact_created(self, rb_setup):
        cp, sm, rb = rb_setup
        state = {"artifact_refs": []}
        evt = {"type": "artifact_created", "payload": {"artifact_id": "a1"}}
        new_state = rb._apply_event(state, evt)
        assert "a1" in new_state["artifact_refs"]

    def test_apply_event_message_added(self, rb_setup):
        cp, sm, rb = rb_setup
        state = {"messages": []}
        evt = {"type": "message_added", "payload": {"message": "hello"}}
        new_state = rb._apply_event(state, evt)
        assert "hello" in new_state["messages"]

    def test_apply_event_phase_changed(self, rb_setup):
        cp, sm, rb = rb_setup
        state = {"phase": "executing"}
        evt = {"type": "phase_changed", "payload": {"phase": "paused"}}
        new_state = rb._apply_event(state, evt)
        assert new_state["phase"] == "paused"


# ============================================================================
# 4. RecoveryOrchestrator Tests (16 cases)
# ============================================================================
class TestRecoveryOrchestrator:
    @pytest.fixture
    def orch_setup(self):
        detector = FailureDetector()
        cp = MockCheckpointManager()
        sm = MockStateManager()
        rb = StateRollback(cp, sm)
        orch = RecoveryOrchestrator(detector, rb)
        return detector, rb, orch, cp, sm

    @pytest.mark.asyncio
    async def test_handle_failure_creates_plan(self, orch_setup):
        detector, rb, orch, cp, sm = orch_setup
        evt = detector.detect_crash("t1", Exception("boom"))
        result = await orch.handle_failure(evt)
        assert isinstance(result, RecoveryResult)

    @pytest.mark.asyncio
    async def test_execute_plan_retry_action(self, orch_setup):
        detector, rb, orch, cp, sm = orch_setup
        plan = RecoveryPlan(
            task_id="t1", failure_type=FailureType.TIMEOUT, actions=[RecoveryAction.RETRY],
        )
        start = time.time()
        result = await orch._execute_plan(plan)
        elapsed = time.time() - start
        assert result.success  # RETRY returns success
        assert elapsed >= 0.8  # ~1s backoff

    @pytest.mark.asyncio
    async def test_execute_plan_rollback_action_success(self, orch_setup):
        detector, rb, orch, cp, sm = orch_setup
        task_id = "t-rollback"
        await sm.initialize(task_id, "goal")
        await cp.save_checkpoint(task_id, {"goal": "goal", "phase": "executing"})
        plan = RecoveryPlan(
            task_id=task_id, failure_type=FailureType.CRASH, actions=[RecoveryAction.ROLLBACK],
        )
        result = await orch._execute_plan(plan)
        assert result.success

    @pytest.mark.asyncio
    async def test_execute_plan_rollback_no_checkpoint(self, orch_setup):
        detector, rb, orch, cp, sm = orch_setup
        plan = RecoveryPlan(
            task_id="t-no-ckpt", failure_type=FailureType.CRASH, actions=[RecoveryAction.ROLLBACK],
        )
        result = await orch._execute_plan(plan)
        assert not result.success

    @pytest.mark.asyncio
    async def test_execute_plan_failover_action(self, orch_setup):
        detector, rb, orch, cp, sm = orch_setup
        plan = RecoveryPlan(
            task_id="t1", failure_type=FailureType.NETWORK, actions=[RecoveryAction.FAILOVER],
        )
        start = time.time()
        result = await orch._execute_plan(plan)
        elapsed = time.time() - start
        assert result.success
        assert elapsed >= 0.8

    @pytest.mark.asyncio
    async def test_execute_plan_skip_action(self, orch_setup):
        detector, rb, orch, cp, sm = orch_setup
        plan = RecoveryPlan(
            task_id="t1", failure_type=FailureType.SANDBOX_FAILURE,
            actions=[RecoveryAction.SKIP, RecoveryAction.HUMAN_INTERVENTION],
        )
        result = await orch._execute_plan(plan)
        assert not result.success
        assert result.failure_reason is not None

    @pytest.mark.asyncio
    async def test_execute_plan_human_intervention(self, orch_setup):
        detector, rb, orch, cp, sm = orch_setup
        plan = RecoveryPlan(
            task_id="t1", failure_type=FailureType.UNKNOWN, actions=[RecoveryAction.HUMAN_INTERVENTION],
        )
        result = await orch._execute_plan(plan)
        assert not result.success

    @pytest.mark.asyncio
    async def test_execute_plan_exhausted(self, orch_setup):
        detector, rb, orch, cp, sm = orch_setup
        plan = RecoveryPlan(
            task_id="t-no-hope", failure_type=FailureType.CRASH, actions=[],  # empty
        )
        result = await orch._execute_plan(plan)
        assert not result.success

    @pytest.mark.asyncio
    async def test_get_active_plan(self, orch_setup):
        detector, rb, orch, cp, sm = orch_setup
        plan = RecoveryPlan(
            task_id="t-direct", failure_type=FailureType.CRASH, actions=[RecoveryAction.RETRY],
        )
        orch._active_plans["t-direct"] = plan
        result = orch.get_active_plan("t-direct")
        assert result is not None
        assert result.task_id == "t-direct"
        assert result.failure_type == FailureType.CRASH

    def test_get_active_plan_none(self, orch_setup):
        detector, rb, orch, cp, sm = orch_setup
        assert orch.get_active_plan("nonexistent") is None

    @pytest.mark.asyncio
    async def test_retry_then_rollback_sequence(self, orch_setup):
        detector, rb, orch, cp, sm = orch_setup
        task_id = "t-seq"
        await sm.initialize(task_id, "goal")
        await cp.save_checkpoint(task_id, {"goal": "goal", "phase": "executing"})
        plan = RecoveryPlan(
            task_id=task_id, failure_type=FailureType.CRASH,
            actions=[RecoveryAction.RETRY, RecoveryAction.ROLLBACK], max_attempts=2,
        )
        result = await orch._execute_plan(plan)
        assert result.success  # RETRY succeeds first

    @pytest.mark.asyncio
    async def test_multiple_failures_isolate_plans(self, orch_setup):
        detector, rb, orch, cp, sm = orch_setup
        plan1 = RecoveryPlan(task_id="t1", failure_type=FailureType.CRASH, actions=[RecoveryAction.ROLLBACK])
        plan2 = RecoveryPlan(task_id="t2", failure_type=FailureType.OOM, actions=[RecoveryAction.RETRY])
        orch._active_plans["t1"] = plan1
        orch._active_plans["t2"] = plan2
        assert orch.get_active_plan("t1").failure_type == FailureType.CRASH
        assert orch.get_active_plan("t2").failure_type == FailureType.OOM

    @pytest.mark.asyncio
    async def test_handle_failure_result_types(self, orch_setup):
        detector, rb, orch, cp, sm = orch_setup
        orch._active_plans["t1"] = RecoveryPlan(
            task_id="t1", failure_type=FailureType.UNKNOWN,
            actions=[RecoveryAction.HUMAN_INTERVENTION],
        )
        plan = orch.get_active_plan("t1")
        result = await orch._execute_plan(plan)
        assert not result.success

    def test_orchestrator_injects_detector_and_rollback(self):
        detector = FailureDetector()
        cp = MockCheckpointManager()
        sm = MockStateManager()
        rb = StateRollback(cp, sm)
        orch = RecoveryOrchestrator(detector, rb)
        assert orch.detector is detector
        assert orch.rollback is rb
