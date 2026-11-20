"""
W19: RuntimeKernel 集成测试
"""
import asyncio
import uuid
import pytest
import pytest_asyncio

from app.runtime.kernel import (
    RuntimeKernel,
    TaskRequest,
    TaskPhase,
    KernelStatus,
)
from app.runtime.policy_engine import PolicyDecision


# ============================================================================
# Lightweight Mocks
# ============================================================================

class MockStateManager:
    def __init__(self):
        self._data = {}

    async def initialize(self, task_id, goal):
        self._data[task_id] = {"goal": goal, "phase": "created",
                                 "messages": [], "artifact_refs": []}

    async def load(self, task_id):
        return self._data.get(task_id, {})

    async def save(self, task_id, state):
        self._data[task_id] = state

    async def update_field(self, task_id, patches):
        if task_id not in self._data:
            self._data[task_id] = {}
        self._data[task_id].update(patches)


class MockCheckpointManager:
    def __init__(self):
        self._ckpts = {}
        self._seq = {}

    async def save_checkpoint(self, task_id, state):
        seq = self._seq.get(task_id, 0) + 1
        self._seq[task_id] = seq
        self._ckpts[task_id] = {"seq": seq, "snapshot": dict(state)}
        return seq

    async def load_latest(self, task_id):
        ckpt = self._ckpts.get(task_id)
        if ckpt:
            Ckpt = type("Ckpt", (), {})
            Ckpt.state_snapshot = ckpt["snapshot"]
            Ckpt.event_seq_num = ckpt["seq"]
            return Ckpt()
        return None


class MockScheduler:
    def __init__(self):
        self.queue = []

    async def submit(self, task):
        self.queue.append(task)
        R = type("R", (), {})
        R.status = "submitted"
        return R()

    async def submit_spec(self, **kwargs):
        R = type("R", (), {})
        R.status = "ok"
        return R()


class MockPolicyEngine:
    def __init__(self):
        self.calls = []

    def check(self, **kwargs):
        self.calls.append(kwargs)
        R = type("R", (), {})
        R.decision = PolicyDecision.ALLOW
        R.reason = ""
        return R()

    def add_policy(self, *args, **kwargs):
        pass


class MockModelRouter:
    def __init__(self):
        self.calls = []

    async def route(self, **kwargs):
        from app.runtime.model_router.models import RoutingDecision, ModelSpec
        self.calls.append(kwargs)
        return RoutingDecision(
            model=ModelSpec(name="test-model", provider="mock"),
            reason="test",
            estimated_cost=0.0,
            estimated_tokens=100,
        )


class MockLoopDetector:
    def __init__(self):
        C = type("C", (), {})
        C.max_total_iterations = 1000
        self.config = C()
        self._counts = {}

    def check(self, **kwargs):
        from app.runtime.loop_detector.models import LoopDecision, LoopAction
        return LoopDecision(is_loop=False, reason="", action=LoopAction.PAUSE)

    def reset_task(self, task_id):
        self._counts.pop(task_id, None)


class MockSandboxManager:
    async def create_session(self, *args, **kwargs):
        S = type("S", (), {})
        S.id = "s1"
        return S()


class MockEventBus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


class FakeRecoveryManager:
    """Fake recovery manager with async replay_events"""
    async def replay_events(self, *a, **kw):
        return []


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def kernel():
    k = RuntimeKernel(
        state_manager=MockStateManager(),
        scheduler=MockScheduler(),
        checkpoint_manager=MockCheckpointManager(),
        policy_engine=MockPolicyEngine(),
        model_router=MockModelRouter(),
        loop_detector=MockLoopDetector(),
        sandbox_manager=MockSandboxManager(),
        event_bus=MockEventBus(),
    )
    return k


@pytest_asyncio.fixture
async def started_kernel(kernel):
    await kernel.start()
    yield kernel
    await kernel.stop()


# ============================================================================
# Test: Task Submission
# ============================================================================

class TestSubmitTask:
    @pytest.mark.asyncio
    async def test_submit_creates_task_record(self, kernel):
        await kernel.start()
        task_id = await kernel.submit_task(TaskRequest(goal_description="test goal"))
        task = kernel.get_task(task_id)
        assert task is not None
        assert task.goal == "test goal"
        assert task.phase == TaskPhase.CREATED

    @pytest.mark.asyncio
    async def test_submit_initializes_state(self, kernel):
        await kernel.start()
        task_id = await kernel.submit_task(TaskRequest(goal_description="init state"))
        state = await kernel.state_mgr.load(task_id)
        assert state["goal"] == "init state"
        assert state["phase"] == TaskPhase.CREATED.value

    @pytest.mark.asyncio
    async def test_submit_returns_valid_uuid(self, kernel):
        await kernel.start()
        task_id = await kernel.submit_task(TaskRequest(goal_description="uuid test"))
        uuid.UUID(task_id, version=4)

    @pytest.mark.asyncio
    async def test_submit_publishes_event(self, kernel):
        await kernel.start()
        task_id = await kernel.submit_task(TaskRequest(goal_description="pub event"))
        assert len(kernel.event_bus.events) >= 1
        event = kernel.event_bus.events[-1]
        assert event.type == "TASK_CREATED"
        assert event.task_id == task_id

    @pytest.mark.asyncio
    async def test_submit_policy_deny_raises(self, kernel):
        R = type("R", (), {})
        R.decision = PolicyDecision.DENY
        R.reason = "no budget"
        kernel.policy_engine.check = lambda **kw: R()
        with pytest.raises(PermissionError, match="rejected by policy"):
            await kernel.submit_task(TaskRequest(goal_description="should fail"))

    @pytest.mark.asyncio
    async def test_submit_adds_to_scheduler_queue(self, kernel):
        await kernel.start()
        task_id = await kernel.submit_task(TaskRequest(goal_description="sched"))
        assert len(kernel.scheduler.queue) == 1
        assert kernel.scheduler.queue[0].task_id == task_id


# ============================================================================
# Test: Task Lifecycle
# ============================================================================

class TestTaskLifecycle:
    @pytest.mark.asyncio
    async def test_pause_task(self, started_kernel):
        k = started_kernel
        task_id = await k.submit_task(TaskRequest(goal_description="pause me"))
        await k.pause_task(task_id, reason="manual")
        task = k.get_task(task_id)
        assert task.phase == TaskPhase.PAUSED

    @pytest.mark.asyncio
    async def test_pause_publishes_event(self, started_kernel):
        k = started_kernel
        task_id = await k.submit_task(TaskRequest(goal_description="pause event"))
        await k.pause_task(task_id, reason="test")
        event_types = [e.type for e in k.event_bus.events]
        assert "TASK_PAUSED" in event_types

    @pytest.mark.asyncio
    async def test_resume_task(self, started_kernel):
        k = started_kernel
        task_id = await k.submit_task(TaskRequest(goal_description="resume me"))
        await k.pause_task(task_id)
        await k.resume_task(task_id)
        task = k.get_task(task_id)
        assert task.phase == TaskPhase.EXECUTING

    @pytest.mark.asyncio
    async def test_cancel_task(self, started_kernel):
        k = started_kernel
        task_id = await k.submit_task(TaskRequest(goal_description="cancel me"))
        await k.cancel_task(task_id)
        task = k.get_task(task_id)
        assert task.phase == TaskPhase.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_publishes_event(self, started_kernel):
        k = started_kernel
        task_id = await k.submit_task(TaskRequest(goal_description="cancel event"))
        await k.cancel_task(task_id)
        event_types = [e.type for e in k.event_bus.events]
        assert "TASK_CANCELLED" in event_types

    @pytest.mark.asyncio
    async def test_pause_saves_checkpoint(self, started_kernel):
        k = started_kernel
        task_id = await k.submit_task(TaskRequest(goal_description="ckpt on pause"))
        await k.state_mgr.save(task_id, {"goal": "ckpt on pause", "phase": "executing"})
        await k.pause_task(task_id)
        ckpt = await k.checkpoint_mgr.load_latest(task_id)
        assert ckpt is not None

    @pytest.mark.asyncio
    async def test_resume_with_approval_data(self, started_kernel):
        k = started_kernel
        task_id = await k.submit_task(TaskRequest(goal_description="approval"))
        await k.pause_task(task_id)
        await k.resume_task(task_id, approval_data={"approved": True})
        state = await k.state_mgr.load(task_id)
        assert state.get("approval_result") == {"approved": True}

    @pytest.mark.asyncio
    async def test_get_nonexistent_task_returns_none(self, kernel):
        assert kernel.get_task("nonexistent-id") is None

    @pytest.mark.asyncio
    async def test_cancel_clears_loop_detector(self, started_kernel):
        k = started_kernel
        task_id = await k.submit_task(TaskRequest(goal_description="clear loop"))
        k.loop_detector._counts[task_id] = 5
        await k.cancel_task(task_id)
        assert task_id not in k.loop_detector._counts


# ============================================================================
# Test: Kernel Status
# ============================================================================

class TestKernelStatus:
    @pytest.mark.asyncio
    async def test_status_after_submit(self, started_kernel):
        k = started_kernel
        await k.submit_task(TaskRequest(goal_description="status 1"))
        await k.submit_task(TaskRequest(goal_description="status 2"))
        status = k.get_status()
        assert status.active_tasks == 2
        assert status.uptime_seconds >= 0

    @pytest.mark.asyncio
    async def test_status_uptime_increases(self, started_kernel):
        k = started_kernel
        t0 = k.get_status().uptime_seconds
        await asyncio.sleep(0.05)
        t1 = k.get_status().uptime_seconds
        assert t1 > t0

    @pytest.mark.asyncio
    async def test_list_tasks_empty(self, kernel):
        tasks = kernel.list_tasks()
        assert tasks == []

    @pytest.mark.asyncio
    async def test_list_tasks_by_phase(self, kernel):
        await kernel.start()
        t1 = await kernel.submit_task(TaskRequest(goal_description="L1"))
        await kernel.pause_task(t1)
        paused = kernel.list_tasks(phase=TaskPhase.PAUSED.value)
        assert len(paused) == 1
        assert paused[0].task_id == t1


# ============================================================================
# Test: Checkpoint + Recovery
# ============================================================================

class TestRecovery:
    @pytest.mark.asyncio
    async def test_recover_from_checkpoint(self, started_kernel):
        k = started_kernel
        task_id = await k.submit_task(TaskRequest(goal_description="recover"))
        await k.state_mgr.save(task_id, {"goal": "recover", "phase": "executing", "data": "v1"})
        await k.checkpoint_mgr.save_checkpoint(task_id, await k.state_mgr.load(task_id))
        await k.state_mgr.save(task_id, {"goal": "recover", "phase": "corrupted"})
        await k.recover_task(task_id)
        state = await k.state_mgr.load(task_id)
        assert state["phase"] == "executing"

    @pytest.mark.asyncio
    async def test_recover_task_not_found(self, kernel):
        await kernel.start()
        with pytest.raises(ValueError, match="Task not found"):
            await kernel.recover_task("nonexistent")

    @pytest.mark.asyncio
    async def test_recover_publishes_event(self, started_kernel):
        k = started_kernel
        task_id = await k.submit_task(TaskRequest(goal_description="recover event"))
        await k.state_mgr.save(task_id, {"goal": "recover event", "phase": "executing"})
        await k.checkpoint_mgr.save_checkpoint(task_id, await k.state_mgr.load(task_id))
        await k.recover_task(task_id)
        assert True


# ============================================================================
# Test: Model Router Integration
# ============================================================================

class TestModelRouterIntegration:
    @pytest.mark.asyncio
    async def test_model_router_called_during_execution(self, started_kernel):
        k = started_kernel
        task_id = await k.submit_task(TaskRequest(goal_description="model route"))
        routing = await k.model_router.route(
            task_id=task_id, capabilities=[], complexity=None
        )
        assert routing.model.name == "test-model"

    @pytest.mark.asyncio
    async def test_model_router_passes_task_metadata(self, started_kernel):
        k = started_kernel
        task_id = await k.submit_task(
            TaskRequest(goal_description="meta", metadata={"complexity": "high"})
        )
        task = k.get_task(task_id)
        await k.model_router.route(
            task_id=task_id,
            capabilities=task.metadata.get("required_capabilities", []),
            complexity=task.metadata.get("complexity"),
        )
        assert len(k.model_router.calls) == 1
        assert k.model_router.calls[0]["task_id"] == task_id


# ============================================================================
# Test: Policy Engine Integration
# ============================================================================

class TestPolicyIntegration:
    @pytest.mark.asyncio
    async def test_policy_called_on_submit(self, kernel):
        await kernel.start()
        await kernel.submit_task(TaskRequest(goal_description="policy check"))
        assert len(kernel.policy_engine.calls) >= 1

    @pytest.mark.asyncio
    async def test_policy_warn_does_not_block(self, started_kernel):
        k = started_kernel
        R = type("R", (), {})
        R.decision = PolicyDecision.WARN
        R.reason = "approaching limit"
        k.policy_engine.check = lambda **kw: R()
        task_id = await k.submit_task(TaskRequest(goal_description="warn test"))
        assert task_id is not None


# ============================================================================
# Test: Loop Detector Integration
# ============================================================================

class TestLoopDetectorIntegration:
    @pytest.mark.asyncio
    async def test_loop_detector_reset_on_cancel(self, started_kernel):
        k = started_kernel
        task_id = await k.submit_task(TaskRequest(goal_description="loop reset"))
        k.loop_detector._counts[task_id] = 99
        await k.cancel_task(task_id)
        assert task_id not in k.loop_detector._counts

    @pytest.mark.asyncio
    async def test_loop_detected_pauses_task(self, started_kernel):
        k = started_kernel
        task_id = await k.submit_task(TaskRequest(goal_description="loop pause"))
        await k.pause_task(task_id, reason="test loop")
        task = k.get_task(task_id)
        assert task.phase == TaskPhase.PAUSED


# ============================================================================
# Test: inject_recovery_manager
# ============================================================================

class TestRecoveryManagerInjection:
    @pytest.mark.asyncio
    async def test_inject_recovery_manager(self, kernel):
        await kernel.start()
        fake_rm = object()
        await kernel.inject_recovery_manager(fake_rm)
        assert kernel._recovery_mgr is fake_rm

    @pytest.mark.asyncio
    async def test_recovery_manager_used_in_recover(self, kernel):
        await kernel.start()
        k = kernel
        task_id = await k.submit_task(TaskRequest(goal_description="rm inject"))
        await k.state_mgr.save(task_id, {"goal": "rm inject", "phase": "executing"})
        await k.checkpoint_mgr.save_checkpoint(task_id, await k.state_mgr.load(task_id))
        fake_rm = FakeRecoveryManager()
        await k.inject_recovery_manager(fake_rm)
        await k.recover_task(task_id)
        assert k._recovery_mgr is fake_rm


# ============================================================================
# Test: start / stop
# ============================================================================

class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_sets_running(self, kernel):
        assert not kernel._running
        await kernel.start()
        assert kernel._running
        assert kernel._start_time > 0

    @pytest.mark.asyncio
    async def test_stop_sets_not_running(self, started_kernel):
        assert started_kernel._running
        await started_kernel.stop()
        assert not started_kernel._running

    @pytest.mark.asyncio
    async def test_stop_cancels_executors(self, kernel):
        await kernel.start()
        k = kernel
        task_id = await k.submit_task(TaskRequest(goal_description="stop executors"))
        fake_task = asyncio.create_task(asyncio.sleep(10))
        k._executors[task_id] = fake_task
        await k.stop()
        await asyncio.sleep(0.01)
        assert fake_task.done()
        assert len(k._executors) == 0

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self, kernel):
        await kernel.start()
        t0 = kernel._start_time
        await asyncio.sleep(0.01)
        await kernel.start()
        assert kernel._start_time == t0

    @pytest.mark.asyncio
    async def test_get_status_before_start_returns_zero_uptime(self, kernel):
        status = kernel.get_status()
        assert status.uptime_seconds == 0.0
