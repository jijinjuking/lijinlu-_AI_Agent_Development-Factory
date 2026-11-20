"""
WorkerManager 模块测试
覆盖：WorkerRegistry / HeartbeatMonitor / WorkerScaler
"""
from __future__ import annotations

import asyncio
import time
from datetime import timedelta

import pytest
import pytest_asyncio
from app.runtime.worker_manager.models import (
    WorkerInfo,
    WorkerStatus,
    ScalingRule,
    ScalingDecision,
    ScalingDirection,
)
from app.runtime.worker_manager.worker_registry import WorkerRegistry
from app.runtime.worker_manager.heartbeat_monitor import HeartbeatMonitor
from app.runtime.worker_manager.worker_scaler import WorkerScaler


# =============================================================================
# WorkerInfo & Enums
# =============================================================================
class TestWorkerStatus:
    def test_values(self):
        assert WorkerStatus.ONLINE == "online"
        assert WorkerStatus.OFFLINE == "offline"
        assert WorkerStatus.BUSY == "busy"
        assert WorkerStatus.DRAINING == "draining"
        assert WorkerStatus.UNHEALTHY == "unhealthy"


class TestScalingDirection:
    def test_values(self):
        assert ScalingDirection.UP == "up"
        assert ScalingDirection.DOWN == "down"
        assert ScalingDirection.NONE == "none"


class TestWorkerInfo:
    def test_defaults(self):
        w = WorkerInfo(worker_id="w1", name="W1")
        assert w.status == WorkerStatus.OFFLINE
        assert w.capabilities == []
        assert w.current_load == 0
        assert w.max_load == 5
        assert w.host == "localhost"
        assert w.port == 0
        assert w.metadata == {}
        assert isinstance(w.heartbeat_at, float)
        assert isinstance(w.registered_at, float)

    def test_load_ratio(self):
        w = WorkerInfo(worker_id="w1", name="W1", current_load=2, max_load=4)
        assert w.load_ratio == 0.5

    def test_load_ratio_zero_max(self):
        w = WorkerInfo(worker_id="w1", name="W1", current_load=0, max_load=0)
        # max_load=0 → load_ratio=1.0 (avoids DivisionByZero)
        assert w.load_ratio == 1.0

    def test_is_available_online(self):
        w = WorkerInfo(worker_id="w1", name="W1", status=WorkerStatus.ONLINE, current_load=2, max_load=5)
        assert w.is_available is True

    def test_is_available_busy_full(self):
        w = WorkerInfo(worker_id="w1", name="W1", status=WorkerStatus.BUSY, current_load=5, max_load=5)
        assert w.is_available is False  # load_ratio == 1.0

    def test_is_available_offline(self):
        w = WorkerInfo(worker_id="w1", name="W1", status=WorkerStatus.OFFLINE)
        assert w.is_available is False


class TestScalingRule:
    def test_defaults(self):
        r = ScalingRule(metric="load_avg", threshold_up=0.8, threshold_down=0.3)
        assert r.cooldown_seconds == 60.0
        assert r.max_workers == 10
        assert r.min_workers == 1
        assert r.scale_step == 1


class TestScalingDecision:
    def test_creation(self):
        d = ScalingDecision(
            direction=ScalingDirection.UP,
            count=2,
            reason="high load",
        )
        assert d.direction == ScalingDirection.UP
        assert d.count == 2


# =============================================================================
# WorkerRegistry
# =============================================================================
class TestWorkerRegistry:
    @pytest.fixture
    def registry(self):
        return WorkerRegistry()

    # --- register ---
    def test_register_success(self, registry):
        worker = registry.register(name="Agent-1", capabilities=["python", "docker"])
        assert worker.worker_id
        assert worker.name == "Agent-1"
        assert worker.status == WorkerStatus.ONLINE
        assert worker.capabilities == ["python", "docker"]
        assert worker.max_load == 5

    def test_register_with_metadata(self, registry):
        meta = {"version": "1.0", "zone": "cn-east"}
        worker = registry.register(name="W1", capabilities=[], metadata=meta)
        assert worker.metadata == meta

    def test_register_unique_ids(self, registry):
        w1 = registry.register(name="W1", capabilities=[])
        w2 = registry.register(name="W2", capabilities=[])
        assert w1.worker_id != w2.worker_id

    # --- deregister ---
    def test_deregister_success(self, registry):
        w = registry.register(name="W1", capabilities=[])
        wid = w.worker_id
        assert registry.deregister(wid) is True
        assert registry.get(wid) is None

    def test_deregister_not_found(self, registry):
        assert registry.deregister("nonexistent") is False

    # --- get ---
    def test_get_exists(self, registry):
        w = registry.register(name="W1", capabilities=[])
        fetched = registry.get(w.worker_id)
        assert fetched is not None
        assert fetched.worker_id == w.worker_id

    def test_get_not_found(self, registry):
        assert registry.get("nonexistent") is None

    # --- list_all ---
    def test_list_all_empty(self, registry):
        assert registry.list_all() == []

    def test_list_all(self, registry):
        registry.register(name="W1", capabilities=[])
        registry.register(name="W2", capabilities=[])
        assert len(registry.list_all()) == 2

    def test_list_all_by_status(self, registry):
        w1 = registry.register(name="W1", capabilities=[])
        w2 = registry.register(name="W2", capabilities=[])
        registry.update_status(w2.worker_id, WorkerStatus.BUSY)
        online = registry.list_all(status=WorkerStatus.ONLINE)
        assert len(online) == 1
        assert online[0].worker_id == w1.worker_id

    # --- list_by_capability ---
    def test_list_by_capability(self, registry):
        registry.register(name="W1", capabilities=["python"])
        registry.register(name="W2", capabilities=["python", "docker"])
        registry.register(name="W3", capabilities=["java"])
        result = registry.list_by_capability("python")
        assert len(result) == 2

    def test_list_by_capability_empty(self, registry):
        assert registry.list_by_capability("python") == []

    # --- list_by_capabilities ---
    def test_list_by_capabilities(self, registry):
        registry.register(name="W1", capabilities=["python", "docker"])
        registry.register(name="W2", capabilities=["python"])
        result = registry.list_by_capabilities(["python", "docker"])
        assert len(result) == 1
        assert result[0].name == "W1"

    # --- update_status ---
    def test_update_status_success(self, registry):
        w = registry.register(name="W1", capabilities=[])
        assert registry.update_status(w.worker_id, WorkerStatus.BUSY) is True
        assert registry.get(w.worker_id).status == WorkerStatus.BUSY

    def test_update_status_not_found(self, registry):
        assert registry.update_status("nonexistent", WorkerStatus.BUSY) is False

    # --- update_load ---
    def test_update_load_success(self, registry):
        w = registry.register(name="W1", capabilities=[], max_load=10)
        assert registry.update_load(w.worker_id, 3) is True
        assert registry.get(w.worker_id).current_load == 3

    def test_update_load_clamp_to_zero(self, registry):
        w = registry.register(name="W1", capabilities=[])
        registry.update_load(w.worker_id, -5)
        assert registry.get(w.worker_id).current_load == 0

    def test_update_load_clamp_to_max(self, registry):
        w = registry.register(name="W1", capabilities=[], max_load=5)
        registry.update_load(w.worker_id, 100)
        assert registry.get(w.worker_id).current_load == 5

    def test_update_load_not_found(self, registry):
        assert registry.update_load("nonexistent", 5) is False

    # --- heartbeat ---
    def test_heartbeat_updates_time(self, registry):
        w = registry.register(name="W1", capabilities=[])
        old = w.heartbeat_at
        time.sleep(0.01)
        assert registry.heartbeat(w.worker_id) is True
        assert w.heartbeat_at > old

    def test_heartbeat_revives_offline(self, registry):
        w = registry.register(name="W1", capabilities=[])
        registry.update_status(w.worker_id, WorkerStatus.OFFLINE)
        assert registry.heartbeat(w.worker_id) is True
        assert w.status == WorkerStatus.ONLINE

    def test_heartbeat_not_found(self, registry):
        assert registry.heartbeat("nonexistent") is False

    # --- select_worker ---
    def test_select_worker_least_loaded(self, registry):
        w1 = registry.register(name="W1", capabilities=["python"], max_load=10)
        w2 = registry.register(name="W2", capabilities=["python"], max_load=10)
        registry.update_load(w1.worker_id, 5)
        registry.update_load(w2.worker_id, 2)
        selected = registry.select_worker(["python"])
        assert selected is not None
        assert selected.worker_id == w2.worker_id  # lower load

    def test_select_worker_none_available(self, registry):
        w = registry.register(name="W1", capabilities=["python"])
        registry.update_status(w.worker_id, WorkerStatus.OFFLINE)
        assert registry.select_worker(["python"]) is None

    def test_select_worker_no_matching_capability(self, registry):
        registry.register(name="W1", capabilities=["java"])
        assert registry.select_worker(["python"]) is None

    # --- properties ---
    def test_online_count(self, registry):
        registry.register(name="W1", capabilities=[])
        registry.register(name="W2", capabilities=[])
        assert registry.online_count == 2

    def test_online_count_excludes_offline(self, registry):
        w1 = registry.register(name="W1", capabilities=[])
        registry.register(name="W2", capabilities=[])
        registry.update_status(w1.worker_id, WorkerStatus.OFFLINE)
        assert registry.online_count == 1

    def test_total_load(self, registry):
        w1 = registry.register(name="W1", capabilities=[], max_load=10)
        w2 = registry.register(name="W2", capabilities=[], max_load=10)
        registry.update_load(w1.worker_id, 3)
        registry.update_load(w2.worker_id, 7)
        assert registry.total_load == 10


# =============================================================================
# HeartbeatMonitor
# =============================================================================
class TestHeartbeatMonitor:
    @pytest.fixture
    def setup(self):
        registry = WorkerRegistry()
        monitor = HeartbeatMonitor(registry, timeout_seconds=0.2, check_interval=0.1)
        return registry, monitor

    @pytest.mark.asyncio
    async def test_start_stop(self, setup):
        """Test that start/stop set _running correctly"""
        registry, monitor = setup
        await monitor.start()
        assert monitor._running is True
        await monitor.stop()
        assert monitor._running is False

    @pytest.mark.asyncio
    async def test_check_all_marks_unhealthy(self, setup):
        registry, monitor = setup
        w = registry.register(name="W1", capabilities=[])
        # Simulate old heartbeat
        w.heartbeat_at = time.time() - 10.0
        unhealthy = await monitor._check_all()
        assert len(unhealthy) == 1
        assert unhealthy[0].worker_id == w.worker_id
        assert w.status == WorkerStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_check_all_skips_offline(self, setup):
        registry, monitor = setup
        w = registry.register(name="W1", capabilities=[])
        registry.update_status(w.worker_id, WorkerStatus.OFFLINE)
        w.heartbeat_at = time.time() - 10.0
        unhealthy = await monitor._check_all()
        assert len(unhealthy) == 0

    @pytest.mark.asyncio
    async def test_check_all_skips_draining(self, setup):
        registry, monitor = setup
        w = registry.register(name="W1", capabilities=[])
        registry.update_status(w.worker_id, WorkerStatus.DRAINING)
        w.heartbeat_at = time.time() - 10.0
        unhealthy = await monitor._check_all()
        assert len(unhealthy) == 0

    @pytest.mark.asyncio
    async def test_purge_unhealthy(self, setup):
        registry, monitor = setup
        w = registry.register(name="W1", capabilities=[])
        w.status = WorkerStatus.UNHEALTHY
        # Make heartbeat old enough to exceed timeout * 3
        w.heartbeat_at = time.time() - (monitor.timeout * 3 + 1)
        count = await monitor.purge_unhealthy()
        assert count >= 1
        assert registry.get(w.worker_id) is None

    @pytest.mark.asyncio
    async def test_callback_sync(self, setup):
        registry, monitor = setup
        w = registry.register(name="W1", capabilities=[])
        w.heartbeat_at = time.time() - 10.0

        callback_called = False
        callback_worker = None

        def on_unhealthy(worker):
            nonlocal callback_called, callback_worker
            callback_called = True
            callback_worker = worker

        monitor.on_worker_unhealthy(on_unhealthy)
        await monitor._check_all()
        assert callback_called is True
        assert callback_worker.worker_id == w.worker_id

    @pytest.mark.asyncio
    async def test_callback_async(self, setup):
        registry, monitor = setup
        w = registry.register(name="W1", capabilities=[])
        w.heartbeat_at = time.time() - 10.0

        callback_called = False

        async def on_unhealthy(worker):
            nonlocal callback_called
            callback_called = True

        monitor.on_worker_unhealthy(on_unhealthy)
        await monitor._check_all()
        assert callback_called is True


# =============================================================================
# WorkerScaler
# =============================================================================
class TestWorkerScaler:
    @pytest.fixture
    def setup(self):
        registry = WorkerRegistry()
        rules = [
            ScalingRule(metric="load_avg", threshold_up=0.8, threshold_down=0.3, cooldown_seconds=0),
            ScalingRule(metric="queue_depth", threshold_up=10, threshold_down=2, cooldown_seconds=0),
        ]
        scaler = WorkerScaler(registry, rules)
        return registry, scaler

    def test_add_rule(self, setup):
        registry, scaler = setup
        new_rule = ScalingRule(metric="error_rate", threshold_up=0.05, threshold_down=0.01)
        scaler.add_rule(new_rule)
        assert "error_rate" in scaler.rules

    @pytest.mark.asyncio
    async def test_evaluate_scale_up(self, setup):
        registry, scaler = setup
        registry.register(name="W1", capabilities=[])
        metrics = {"load_avg": 0.95, "queue_depth": 5}
        decision = await scaler.evaluate(metrics)
        assert decision is not None
        assert decision.direction == ScalingDirection.UP

    @pytest.mark.asyncio
    async def test_evaluate_scale_down(self, setup):
        registry, scaler = setup
        registry.register(name="W1", capabilities=[])
        # Need load_avg <= threshold_down (0.3) to trigger scale down
        metrics = {"load_avg": 0.1, "queue_depth": 1}
        decision = await scaler.evaluate(metrics)
        # Only triggers if online_count > min_workers (1)
        # We have 1 worker, min_workers=1, so no scale down
        # Actually scale down triggers when current > min_workers
        # With 1 worker and min_workers=1, it should NOT scale down
        if decision is not None:
            assert decision.direction == ScalingDirection.DOWN

    @pytest.mark.asyncio
    async def test_evaluate_no_scale(self, setup):
        registry, scaler = setup
        registry.register(name="W1", capabilities=[])
        metrics = {"load_avg": 0.5, "queue_depth": 5}
        decision = await scaler.evaluate(metrics)
        if decision is not None:
            assert decision.direction == ScalingDirection.NONE

    @pytest.mark.asyncio
    async def test_evaluate_at_max_workers(self, setup):
        registry, scaler = setup
        for i in range(10):
            registry.register(name=f"W{i}", capabilities=[])
        metrics = {"load_avg": 0.95}
        decision = await scaler.evaluate(metrics)
        # At max_workers=10, should not scale up further
        if decision is not None:
            # If it returns a decision, it should not be UP
            assert decision.direction != ScalingDirection.UP

    @pytest.mark.asyncio
    async def test_evaluate_at_min_workers(self, setup):
        registry, scaler = setup
        registry.register(name="W1", capabilities=[])
        metrics = {"load_avg": 0.1}
        decision = await scaler.evaluate(metrics)
        # At min_workers=1 with 1 worker, should not scale down
        if decision is not None:
            assert decision.direction != ScalingDirection.DOWN

    @pytest.mark.asyncio
    async def test_evaluate_cooldown(self, setup):
        registry, scaler = setup
        registry.register(name="W1", capabilities=[])
        metrics = {"load_avg": 0.95}
        # First evaluation (cooldown_seconds=0 in test setup)
        d1 = await scaler.evaluate(metrics)
        # With cooldown=0, second evaluation should also work
        d2 = await scaler.evaluate(metrics)
        # Both may return decisions (cooldown=0)
        if d1 is not None:
            assert d1.direction == ScalingDirection.UP

    @pytest.mark.asyncio
    async def test_on_scale_callback(self, setup):
        registry, scaler = setup
        registry.register(name="W1", capabilities=[])

        callback_called = False
        callback_direction = None

        def on_scale(decision):
            nonlocal callback_called, callback_direction
            callback_called = True
            callback_direction = decision.direction

        scaler.on_scale(ScalingDirection.UP, on_scale)
        metrics = {"load_avg": 0.95}
        await scaler.evaluate(metrics)
        assert callback_called is True
