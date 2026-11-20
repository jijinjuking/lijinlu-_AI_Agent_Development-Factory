"""
TaskDispatcher 模块测试
覆盖：TaskDispatcher 的 dispatch / complete / fail / cancel / get_results / register_handler
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from app.runtime.scheduler.models import ScheduleResult, TaskStatus
from app.runtime.task_dispatcher import TaskDispatcher


# =============================================================================
# Helpers
# =============================================================================
def make_result(task_id="t-001", worker_id="w-001", model_name="deepseek-chat"):
    return ScheduleResult(
        task_id=task_id,
        status=TaskStatus.QUEUED,
        worker_id=worker_id,
        model_name=model_name,
    )


# =============================================================================
# Init
# =============================================================================
class TestInit:
    def test_init_no_args(self):
        d = TaskDispatcher()
        assert d._workers is None
        assert d._sandbox is None
        assert d._active_dispatches == {}
        assert d._dispatch_handlers == {}
        assert d._results == {}

    def test_init_with_worker_manager(self):
        wm = MagicMock()
        d = TaskDispatcher(worker_manager=wm)
        assert d._workers is wm

    def test_init_with_sandbox_manager(self):
        sm = MagicMock()
        d = TaskDispatcher(sandbox_manager=sm)
        assert d._sandbox is sm


# =============================================================================
# register_handler
# =============================================================================
class TestRegisterHandler:
    def test_register_single(self):
        d = TaskDispatcher()
        def handler(data):
            pass
        d.register_handler("task_dispatched", handler)
        assert "task_dispatched" in d._dispatch_handlers
        assert handler in d._dispatch_handlers["task_dispatched"]

    def test_register_multiple(self):
        d = TaskDispatcher()
        def h1(data):
            pass
        def h2(data):
            pass
        d.register_handler("task_dispatched", h1)
        d.register_handler("task_dispatched", h2)
        assert len(d._dispatch_handlers["task_dispatched"]) == 2

    def test_register_different_events(self):
        d = TaskDispatcher()
        def h1(data):
            pass
        def h2(data):
            pass
        d.register_handler("task_dispatched", h1)
        d.register_handler("task_completed", h2)
        assert "task_dispatched" in d._dispatch_handlers
        assert "task_completed" in d._dispatch_handlers


# =============================================================================
# dispatch
# =============================================================================
class TestDispatch:
    @pytest_asyncio.fixture
    async def d(self):
        return TaskDispatcher()

    @pytest_asyncio.fixture
    async def result(self):
        return make_result()

    @pytest.mark.asyncio
    async def test_dispatch_success(self, d, result):
        ret = await d.dispatch(result)
        assert ret is True
        records = d.get_results("t-001")
        assert len(records) >= 1
        assert records[0]["event"] == "dispatched"

    @pytest.mark.asyncio
    async def test_dispatch_records_worker_and_model(self, d, result):
        result.model_name = "gpt-4"
        await d.dispatch(result)
        records = d.get_results("t-001")
        assert records[0]["worker_id"] == "w-001"
        assert records[0]["model"] == "gpt-4"
        assert "timestamp" in records[0]

    @pytest.mark.asyncio
    async def test_dispatch_with_worker_manager(self, result):
        wm = MagicMock()
        wm.get = MagicMock(return_value=MagicMock(current_load=2))
        wm.update_status = MagicMock()
        wm.update_load = MagicMock()
        d = TaskDispatcher(worker_manager=wm)
        await d.dispatch(result)
        wm.update_status.assert_called_once_with("w-001", "busy")
        wm.update_load.assert_called_once_with("w-001", 3)

    @pytest.mark.asyncio
    async def test_dispatch_triggers_handler(self, d, result):
        called = False
        called_data = None

        def handler(data):
            nonlocal called, called_data
            called = True
            called_data = data

        d.register_handler("task_dispatched", handler)
        await d.dispatch(result)
        assert called is True
        assert called_data["task_id"] == "t-001"

    @pytest.mark.asyncio
    async def test_dispatch_handler_exception_not_raise(self, d, result):
        def bad_handler(data):
            raise RuntimeError("boom")
        d.register_handler("task_dispatched", bad_handler)
        ret = await d.dispatch(result)
        assert ret is True


# =============================================================================
# complete
# =============================================================================
class TestComplete:
    @pytest.mark.asyncio
    async def test_complete_success(self):
        d = TaskDispatcher()
        result = make_result()
        await d.dispatch(result)
        await d.complete("t-001")
        records = d.get_results("t-001")
        complete_events = [r for r in records if r["event"] == "completed"]
        assert len(complete_events) == 1

    @pytest.mark.asyncio
    async def test_complete_triggers_handler(self):
        d = TaskDispatcher()
        called = False
        def handler(data):
            nonlocal called
            called = True
        d.register_handler("task_completed", handler)
        result = make_result()
        await d.dispatch(result)
        await d.complete("t-001")
        assert called is True

    @pytest.mark.asyncio
    async def test_complete_nonexistent(self):
        d = TaskDispatcher()
        await d.complete("nonexistent")


# =============================================================================
# fail
# =============================================================================
class TestFail:
    @pytest.mark.asyncio
    async def test_fail_success(self):
        d = TaskDispatcher()
        result = make_result()
        await d.dispatch(result)
        await d.fail("t-001", "something went wrong")
        records = d.get_results("t-001")
        failed = [r for r in records if r["event"] == "failed"]
        assert len(failed) == 1
        assert failed[0]["error"] == "something went wrong"

    @pytest.mark.asyncio
    async def test_fail_triggers_handler(self):
        d = TaskDispatcher()
        called = False
        def handler(data):
            nonlocal called
            called = True
        d.register_handler("task_failed", handler)
        result = make_result()
        await d.dispatch(result)
        await d.fail("t-001", "error")
        assert called is True

    @pytest.mark.asyncio
    async def test_fail_nonexistent(self):
        d = TaskDispatcher()
        await d.fail("nonexistent", "error")


# =============================================================================
# cancel
# =============================================================================
class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_no_active_task(self):
        d = TaskDispatcher()
        result = make_result()
        await d.dispatch(result)
        # dispatch() does not populate _active_dispatches
        ret = d.cancel("t-001")
        assert ret is False

    @pytest.mark.asyncio
    async def test_cancel_with_active_task(self):
        d = TaskDispatcher()
        # Manually inject an active dispatch task
        async def dummy():
            await asyncio.sleep(10)
        task = asyncio.create_task(dummy())
        d._active_dispatches["t-001"] = task
        ret = d.cancel("t-001")
        assert ret is True
        # Let the cancellation propagate
        await asyncio.sleep(0)
        assert task.cancelled()
        assert "t-001" not in d._active_dispatches

    def test_cancel_nonexistent(self):
        d = TaskDispatcher()
        ret = d.cancel("nonexistent")
        assert ret is False


# =============================================================================
# get_results
# =============================================================================
class TestGetResults:
    @pytest.mark.asyncio
    async def test_get_results_empty(self):
        d = TaskDispatcher()
        results = d.get_results("nonexistent")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_results_after_dispatch(self):
        d = TaskDispatcher()
        result = make_result()
        await d.dispatch(result)
        results = d.get_results("t-001")
        assert len(results) >= 1
        assert "event" in results[0]
        assert "timestamp" in results[0]

    @pytest.mark.asyncio
    async def test_get_results_ordered(self):
        d = TaskDispatcher()
        result = make_result()
        await d.dispatch(result)
        await d.complete("t-001")
        results = d.get_results("t-001")
        timestamps = [r["timestamp"] for r in results]
        assert timestamps == sorted(timestamps)


# =============================================================================
# Integration
# =============================================================================
class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """dispatch → complete → get_results"""
        d = TaskDispatcher()
        result = make_result()
        await d.dispatch(result)
        await d.complete("t-001")
        results = d.get_results("t-001")
        events = [r["event"] for r in results]
        assert "dispatched" in events
        assert "completed" in events

    @pytest.mark.asyncio
    async def test_full_lifecycle_with_failure(self):
        """dispatch → fail → get_results"""
        d = TaskDispatcher()
        result = make_result()
        await d.dispatch(result)
        await d.fail("t-001", "error")
        results = d.get_results("t-001")
        events = [r["event"] for r in results]
        assert "dispatched" in events
        assert "failed" in events

    @pytest.mark.asyncio
    async def test_all_event_handlers(self):
        """Verify all 3 event types trigger handlers"""
        d = TaskDispatcher()
        events = []

        def make_handler(name):
            def handler(data):
                events.append(name)
            return handler

        d.register_handler("task_dispatched", make_handler("dispatched"))
        d.register_handler("task_completed", make_handler("completed"))
        d.register_handler("task_failed", make_handler("failed"))

        result = make_result()
        await d.dispatch(result)
        await d.complete("t-001")

        assert "dispatched" in events
        assert "completed" in events
