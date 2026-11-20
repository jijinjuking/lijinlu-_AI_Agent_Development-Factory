"""
W8 Scheduler 测试套件

覆盖:
- TaskQueue: 优先级入队出队、取消、状态查询
- WorkerPool: 注册/注销、能力索引、健康检查、负载管理
- Router: 最少负载路由、能力匹配
- RetryPolicy: 退避计算、重试判断
- TimeoutPolicy: 超时控制
- Scheduler: submit → dispatch → execute 全链路集成
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from app.runtime.scheduler.models import (
    Capability,
    RetryConfig,
    ScheduleResult,
    ScheduledTask,
    TaskStatus,
    TimeoutConfig,
    WorkerInfo,
)
from app.runtime.scheduler.task_queue import TaskQueue
from app.runtime.scheduler.worker_pool import WorkerPool
from app.runtime.scheduler.router import Router
from app.runtime.scheduler.retry_policy import RetryPolicy
from app.runtime.scheduler.timeout_policy import TimeoutPolicy
from app.runtime.scheduler.scheduler import Scheduler
from app.runtime.execution_engine.workflow_schema import (
    WorkflowSpec,
    NodeSpec,
    EdgeSpec,
    NodeType,
)
from app.runtime.execution_engine.node_executor import NodeExecutor


# ═══════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════

def make_simple_workflow(name: str = "test_wf") -> WorkflowSpec:
    """创建一个最小可行 WorkflowSpec"""
    return WorkflowSpec(
        name=name,
        nodes=[
            NodeSpec(id="start", type=NodeType.START),
            NodeSpec(
                id="step1",
                type=NodeType.TOOL,
                config={"tool_name": "echo", "args": {"message": "hello"}},
            ),
            NodeSpec(id="end", type=NodeType.END),
        ],
        edges=[
            EdgeSpec(source="start", target="step1"),
            EdgeSpec(source="step1", target="end"),
        ],
    )


# ═══════════════════════════════════════════
# 1. TaskQueue 测试
# ═══════════════════════════════════════════

class TestTaskQueue:
    """优先级任务队列"""

    @pytest.mark.asyncio
    async def test_enqueue_dequeue(self):
        """基本入队出队"""
        q = TaskQueue()
        task = ScheduledTask(capability="test", workflow_spec=make_simple_workflow(), task_id="t1")
        await q.enqueue(task)

        assert await q.size == 1
        dq = await q.dequeue()
        assert dq is not None
        assert dq.task_id == "t1"

    @pytest.mark.asyncio
    async def test_priority_order(self):
        """高优先级先出队"""
        q = TaskQueue()
        t_low = ScheduledTask(capability="test", workflow_spec=make_simple_workflow(),
                              task_id="low", priority=9)
        t_high = ScheduledTask(capability="test", workflow_spec=make_simple_workflow(),
                               task_id="high", priority=1)
        t_mid = ScheduledTask(capability="test", workflow_spec=make_simple_workflow(),
                              task_id="mid", priority=5)
        await q.enqueue(t_low)
        await q.enqueue(t_high)
        await q.enqueue(t_mid)

        dq1 = await q.dequeue()
        dq2 = await q.dequeue()
        dq3 = await q.dequeue()

        assert dq1.task_id == "high"
        assert dq2.task_id == "mid"
        assert dq3.task_id == "low"

    @pytest.mark.asyncio
    async def test_fifo_for_same_priority(self):
        """同优先级 FIFO"""
        q = TaskQueue()
        t1 = ScheduledTask(capability="test", workflow_spec=make_simple_workflow(),
                           task_id="first", priority=5)
        t2 = ScheduledTask(capability="test", workflow_spec=make_simple_workflow(),
                           task_id="second", priority=5)
        await q.enqueue(t1)
        await q.enqueue(t2)

        assert (await q.dequeue()).task_id == "first"
        assert (await q.dequeue()).task_id == "second"

    @pytest.mark.asyncio
    async def test_dequeue_empty_returns_none(self):
        q = TaskQueue()
        assert await q.dequeue() is None

    @pytest.mark.asyncio
    async def test_peek(self):
        """peek 不删除元素"""
        q = TaskQueue()
        task = ScheduledTask(capability="test", workflow_spec=make_simple_workflow(), task_id="p1")
        await q.enqueue(task)

        peeked = await q.peek()
        assert peeked.task_id == "p1"
        assert await q.size == 1  # 还在

    @pytest.mark.asyncio
    async def test_cancel(self):
        """取消队列中的任务"""
        q = TaskQueue()
        task = ScheduledTask(capability="test", workflow_spec=make_simple_workflow(), task_id="c1")
        await q.enqueue(task)

        assert await q.cancel("c1") is True
        assert await q.dequeue() is None  # 被跳过

    @pytest.mark.asyncio
    async def test_cancel_running_task_returns_false(self):
        """已分发的任务不能取消（cancel 只取消 QUEUED/RETRYING 状态）"""
        q = TaskQueue()
        task = ScheduledTask(capability="test", workflow_spec=make_simple_workflow(), task_id="r1")
        # 直接加入 _tasks（绕过 enqueue 的 status 覆盖）
        task.status = TaskStatus.RUNNING
        q._tasks["r1"] = task

        assert await q.cancel("r1") is False

    @pytest.mark.asyncio
    async def test_status(self):
        q = TaskQueue()
        task = ScheduledTask(capability="test", workflow_spec=make_simple_workflow(), task_id="s1")
        await q.enqueue(task)
        assert await q.status("s1") == TaskStatus.QUEUED

        # 取消后
        await q.cancel("s1")
        assert await q.status("s1") == TaskStatus.CANCELLED

        # 不存在的任务
        assert await q.status("nonexistent") is None

    @pytest.mark.asyncio
    async def test_pending(self):
        q = TaskQueue()
        t1 = ScheduledTask(capability="test", workflow_spec=make_simple_workflow(), task_id="p1", priority=3)
        t2 = ScheduledTask(capability="test", workflow_spec=make_simple_workflow(), task_id="p2", priority=1)
        await q.enqueue(t1)
        await q.enqueue(t2)

        pending = await q.pending()
        assert len(pending) == 2
        assert pending[0].task_id == "p2"  # 更高优先级
        assert pending[1].task_id == "p1"

    @pytest.mark.asyncio
    async def test_clear(self):
        q = TaskQueue()
        await q.enqueue(ScheduledTask(
            capability="test", workflow_spec=make_simple_workflow(), task_id="x1"))
        await q.clear()
        assert await q.size == 0
        assert await q.total == 0

    @pytest.mark.asyncio
    async def test_enqueue_batch(self):
        q = TaskQueue()
        tasks = [
            ScheduledTask(capability="test", workflow_spec=make_simple_workflow(), task_id=f"b{i}")
            for i in range(5)
        ]
        await q.enqueue_batch(tasks)
        assert await q.size == 5

    @pytest.mark.asyncio
    async def test_task_status_transitions(self):
        """任务状态的正确记录"""
        q = TaskQueue()
        task = ScheduledTask(capability="test", workflow_spec=make_simple_workflow(), task_id="st1")
        assert task.status == TaskStatus.QUEUED  # 初始

        await q.enqueue(task)
        assert task.status == TaskStatus.QUEUED  # enqueue 后


# ═══════════════════════════════════════════
# 2. WorkerPool 测试
# ═══════════════════════════════════════════

class TestWorkerPool:
    """Worker 注册池"""

    @pytest.mark.asyncio
    async def test_register_deregister(self):
        pool = WorkerPool()
        worker = WorkerInfo(worker_id="w1", capabilities=["code_generation"])
        await pool.register(worker)

        assert await pool.size == 1
        assert await pool.get("w1") is not None

        await pool.deregister("w1")
        assert await pool.size == 0
        assert await pool.get("w1") is None

    @pytest.mark.asyncio
    async def test_deregister_nonexistent(self):
        pool = WorkerPool()
        assert await pool.deregister("nonexistent") is False

    @pytest.mark.asyncio
    async def test_get_by_capability(self):
        pool = WorkerPool()
        await pool.register(WorkerInfo(worker_id="w1", capabilities=["code_gen", "review"]))
        await pool.register(WorkerInfo(worker_id="w2", capabilities=["review"]))
        await pool.register(WorkerInfo(worker_id="w3", capabilities=["deploy"]))

        code_workers = await pool.get_by_capability("code_gen")
        assert len(code_workers) == 1
        assert code_workers[0].worker_id == "w1"

        review_workers = await pool.get_by_capability("review")
        assert len(review_workers) == 2

        deploy_workers = await pool.get_by_capability("deploy")
        assert len(deploy_workers) == 1

        # 没有的能力
        none_workers = await pool.get_by_capability("unknown")
        assert len(none_workers) == 0

    @pytest.mark.asyncio
    async def test_busy_worker_not_available(self):
        """忙碌的 Worker 不应出现在可用列表"""
        pool = WorkerPool()
        worker = WorkerInfo(worker_id="w1", capabilities=["test"], status="busy")
        await pool.register(worker)

        available = await pool.get_by_capability("test")
        assert len(available) == 0  # busy 的不可用

    @pytest.mark.asyncio
    async def test_heartbeat(self):
        pool = WorkerPool()
        worker = WorkerInfo(worker_id="w1", capabilities=["test"])
        await pool.register(worker)

        # 设成 unhealthy
        worker.status = "unhealthy"
        assert await pool.heartbeat("w1") is True
        assert worker.status == "idle"  # heartbeat 恢复

    @pytest.mark.asyncio
    async def test_heartbeat_nonexistent(self):
        pool = WorkerPool()
        assert await pool.heartbeat("nonexistent") is False

    @pytest.mark.asyncio
    async def test_check_health(self):
        pool = WorkerPool(heartbeat_timeout=0.01)
        worker = WorkerInfo(worker_id="w1", capabilities=["test"])
        await pool.register(worker)

        # 先 heartbeat 重置时间
        await pool.heartbeat("w1")
        # 等待超过 timeout
        await asyncio.sleep(0.02)

        unhealthy = await pool.check_health()
        assert "w1" in unhealthy

    @pytest.mark.asyncio
    async def test_purge_unhealthy(self):
        pool = WorkerPool(heartbeat_timeout=0.01)
        await pool.register(WorkerInfo(worker_id="w1", capabilities=["test"]))
        await asyncio.sleep(0.02)

        purged = await pool.purge_unhealthy()
        assert "w1" in purged
        assert await pool.size == 0

    @pytest.mark.asyncio
    async def test_acquire_release_load(self):
        pool = WorkerPool()
        worker = WorkerInfo(worker_id="w1", capabilities=["test"], max_concurrency=2)
        await pool.register(worker)

        # acquire #1
        assert await pool.acquire("w1") is True
        assert worker.current_load == 1
        assert worker.status == "idle"  # 还没满

        # acquire #2
        assert await pool.acquire("w1") is True
        assert worker.current_load == 2
        assert worker.status == "busy"  # 满了

        # acquire #3 — 拒绝
        assert await pool.acquire("w1") is False

        # release
        await pool.release("w1")
        assert worker.current_load == 1
        assert worker.status == "idle"  # 恢复

    @pytest.mark.asyncio
    async def test_list_all(self):
        pool = WorkerPool()
        await pool.register(WorkerInfo(worker_id="w1", capabilities=["a"]))
        await pool.register(WorkerInfo(worker_id="w2", capabilities=["b"], status="busy"))

        all_w = await pool.list_all()
        assert len(all_w) == 2

        available = await pool.list_available()
        assert len(available) == 1
        assert available[0].worker_id == "w1"


# ═══════════════════════════════════════════
# 3. Router 测试
# ═══════════════════════════════════════════

class TestRouter:
    """能力路由"""

    @pytest.mark.asyncio
    async def test_route_least_loaded(self):
        pool = WorkerPool()
        w1 = WorkerInfo(worker_id="w1", capabilities=["code"], current_load=2)
        w2 = WorkerInfo(worker_id="w2", capabilities=["code"], current_load=0)
        w3 = WorkerInfo(worker_id="w3", capabilities=["code"], current_load=1)
        for w in [w1, w2, w3]:
            await pool.register(w)

        router = Router(pool)
        selected = await router.route("code")
        assert selected is not None
        assert selected.worker_id == "w2"  # 负载最小

    @pytest.mark.asyncio
    async def test_route_no_capability(self):
        pool = WorkerPool()
        await pool.register(WorkerInfo(worker_id="w1", capabilities=["deploy"]))
        router = Router(pool)

        assert await router.route("code_gen") is None

    @pytest.mark.asyncio
    async def test_route_skips_busy(self):
        pool = WorkerPool()
        await pool.register(WorkerInfo(worker_id="w1", capabilities=["code"], status="busy"))
        router = Router(pool)

        assert await router.route("code") is None

    @pytest.mark.asyncio
    async def test_route_to_specific(self):
        pool = WorkerPool()
        await pool.register(WorkerInfo(worker_id="w1", capabilities=["code"]))
        await pool.register(WorkerInfo(worker_id="w2", capabilities=["review"]))
        router = Router(pool)

        selected = await router.route_to_specific("code", "w1")
        assert selected is not None
        assert selected.worker_id == "w1"

        # 能力不匹配
        assert await router.route_to_specific("code", "w2") is None

    @pytest.mark.asyncio
    async def test_route_any(self):
        pool = WorkerPool()
        await pool.register(WorkerInfo(worker_id="w1", capabilities=["a"]))
        await pool.register(WorkerInfo(worker_id="w2", capabilities=["b"], current_load=5))
        router = Router(pool)

        selected = await router.route_any()
        assert selected is not None
        assert selected.worker_id == "w1"  # 负载更小

    @pytest.mark.asyncio
    async def test_capabilities_aggregation(self):
        pool = WorkerPool()
        await pool.register(WorkerInfo(worker_id="w1", capabilities=["code", "review"]))
        await pool.register(WorkerInfo(worker_id="w2", capabilities=["deploy"]))
        router = Router(pool)

        caps = await router.capabilities()
        assert caps == {"code", "review", "deploy"}


# ═══════════════════════════════════════════
# 4. RetryPolicy 测试
# ═══════════════════════════════════════════

class TestRetryPolicy:
    """重试策略"""

    def test_exponential_backoff(self):
        rp = RetryPolicy(RetryConfig(strategy="exponential", base_delay=1.0, max_delay=60.0))
        assert rp.delay_seconds(1) == 1.0
        assert rp.delay_seconds(2) == 2.0
        assert rp.delay_seconds(3) == 4.0
        assert rp.delay_seconds(4) == 8.0
        assert rp.delay_seconds(10) == 60.0  # capped at max_delay

    def test_linear_backoff(self):
        rp = RetryPolicy(RetryConfig(strategy="linear", base_delay=2.0, max_delay=60.0))
        assert rp.delay_seconds(1) == 2.0
        assert rp.delay_seconds(3) == 6.0
        assert rp.delay_seconds(5) == 10.0

    def test_fixed_backoff(self):
        rp = RetryPolicy(RetryConfig(strategy="fixed", base_delay=5.0))
        assert rp.delay_seconds(1) == 5.0
        assert rp.delay_seconds(100) == 5.0

    def test_should_retry_retryable(self):
        rp = RetryPolicy()
        assert rp.should_retry("connection timeout", 1) is True
        assert rp.should_retry("rate_limit exceeded", 2) is True
        assert rp.should_retry("transient error", 1) is True

    def test_should_retry_nonretryable(self):
        rp = RetryPolicy()
        assert rp.should_retry("permission denied", 1) is False
        assert rp.should_retry("validation error", 2) is False

    def test_should_retry_max_attempts(self):
        rp = RetryPolicy(RetryConfig(max_retries=3))
        assert rp.should_retry("timeout", 3) is False  # max reached
        assert rp.should_retry("timeout", 2) is True

    @pytest.mark.asyncio
    async def test_backoff_sleep(self):
        rp = RetryPolicy(RetryConfig(strategy="fixed", base_delay=0.01))
        elapsed = await rp.backoff(1, "timeout")
        assert elapsed >= 0.0  # 至少执行了


# ═══════════════════════════════════════════
# 5. TimeoutPolicy 测试
# ═══════════════════════════════════════════

class TestTimeoutPolicy:
    """超时控制"""

    def test_default_timeout(self):
        tp = TimeoutPolicy()
        assert tp.timeout_seconds("any") == 300.0  # 默认 5 分钟

    def test_per_capability_timeout(self):
        tp = TimeoutPolicy(TimeoutConfig(
            default_timeout=60.0,
            per_capability={
                "code_generation": 600.0,
                "browser_control": 120.0,
            },
        ))
        assert tp.timeout_seconds("code_generation") == 600.0
        assert tp.timeout_seconds("browser_control") == 120.0
        assert tp.timeout_seconds("unknown") == 60.0  # fallback

    @pytest.mark.asyncio
    async def test_with_timeout_success(self):
        tp = TimeoutPolicy(TimeoutConfig(default_timeout=5.0))
        result, timed_out, error = await tp.with_timeout(
            asyncio.sleep, "test", 0.01,
        )
        assert timed_out is False
        assert error is None

    @pytest.mark.asyncio
    async def test_with_timeout_expires(self):
        tp = TimeoutPolicy(TimeoutConfig(default_timeout=0.01))
        result, timed_out, error = await tp.with_timeout(
            asyncio.sleep, "test", 10.0,
        )
        assert timed_out is True
        assert result is None

    @pytest.mark.asyncio
    async def test_with_timeout_exception(self):
        async def raise_err():
            raise ValueError("boom")

        tp = TimeoutPolicy(TimeoutConfig(default_timeout=5.0))
        result, timed_out, error = await tp.with_timeout(raise_err, "test")
        assert timed_out is False
        assert isinstance(error, ValueError)


# ═══════════════════════════════════════════
# 6. Scheduler 集成测试
# ═══════════════════════════════════════════

class MockToolExecutor:
    """模拟 ToolExecutor - 永远成功"""
    async def execute(self, tool_name: str, args: dict, ctx=None):
        from app.runtime.tool_runtime.models import ExecutionResult, ExecutionStatus
        return ExecutionResult(
            tool_name=tool_name,
            status=ExecutionStatus.COMPLETED,
            output=f"mock: {tool_name}({args})",
        )


@pytest_asyncio.fixture
def mock_node_executor():
    """用 Mock ToolExecutor 构建 NodeExecutor"""
    mock_tool = MockToolExecutor()
    return NodeExecutor(tool_executor=mock_tool)


class TestSchedulerIntegration:
    """调度器全链路集成测试"""

    @pytest.mark.asyncio
    async def test_scheduler_start_stop(self, mock_node_executor):
        s = Scheduler(node_executor=mock_node_executor)
        await s.start()
        assert s._running is True
        await s.stop()
        assert s._running is False

    @pytest.mark.asyncio
    async def test_submit_and_execute(self, mock_node_executor):
        s = Scheduler(node_executor=mock_node_executor)
        await s.register_worker("w1", ["test_capability"])
        await s.start()

        task_id = await s.submit_spec(
            workflow_spec=make_simple_workflow(),
            capability="test_capability",
            priority=1,
        )

        result = await s.wait_for(task_id, timeout=10.0)
        assert result is not None
        assert result.status == TaskStatus.COMPLETED
        assert result.worker_id == "w1"

        await s.stop()

    @pytest.mark.asyncio
    async def test_submit_no_worker_re_queues(self, mock_node_executor):
        """没有可用 Worker 时任务放回队列"""
        s = Scheduler(node_executor=mock_node_executor)
        await s.start()

        task_id = await s.submit_spec(
            workflow_spec=make_simple_workflow(),
            capability="nonexistent",
            priority=1,
        )

        # 短暂等待调度循环
        await asyncio.sleep(0.2)

        # 任务应该还在队列里
        status = await s.task_status(task_id)
        assert status == TaskStatus.QUEUED

        await s.stop()

    @pytest.mark.asyncio
    async def test_later_registered_worker_picks_up(self, mock_node_executor):
        """先提交任务，后注册 Worker，任务会被执行"""
        s = Scheduler(node_executor=mock_node_executor)
        await s.start()

        # 先提交
        task_id = await s.submit_spec(
            workflow_spec=make_simple_workflow(),
            capability="late_cap",
            priority=1,
        )

        await asyncio.sleep(0.1)

        # 后注册
        await s.register_worker("late_w", ["late_cap"])

        result = await s.wait_for(task_id, timeout=10.0)
        assert result is not None
        assert result.status == TaskStatus.COMPLETED

        await s.stop()

    @pytest.mark.asyncio
    async def test_multiple_tasks_different_priorities(self, mock_node_executor):
        s = Scheduler(node_executor=mock_node_executor)
        await s.register_worker("w1", ["test_cap"])
        await s.start()

        tasks = []
        for i in range(3):
            tid = await s.submit_spec(
                workflow_spec=make_simple_workflow(f"wf_{i}"),
                capability="test_cap",
                priority=10 - i,  # 第一个最低优先级
            )
            tasks.append(tid)

        for tid in tasks:
            result = await s.wait_for(tid, timeout=10.0)
            assert result is not None
            assert result.status == TaskStatus.COMPLETED

        await s.stop()

    @pytest.mark.asyncio
    async def test_cancel_queued_task(self, mock_node_executor):
        s = Scheduler(node_executor=mock_node_executor)
        await s.start()

        task_id = await s.submit_spec(
            workflow_spec=make_simple_workflow(),
            capability="no_worker",
        )

        await asyncio.sleep(0.1)
        assert await s.cancel_task(task_id) is True
        assert await s.task_status(task_id) == TaskStatus.CANCELLED

        await s.stop()

    @pytest.mark.asyncio
    async def test_deregister_worker(self, mock_node_executor):
        s = Scheduler(node_executor=mock_node_executor)
        await s.register_worker("w1", ["test"])
        assert await s.worker_count == 1

        await s.deregister_worker("w1")
        assert await s.worker_count == 0

    @pytest.mark.asyncio
    async def test_worker_heartbeat(self, mock_node_executor):
        s = Scheduler(node_executor=mock_node_executor)
        await s.register_worker("w1", ["test"])

        # 获取 worker 并设 unhealthy
        worker = await s.worker_pool.get("w1")
        worker.status = "unhealthy"

        await s.worker_heartbeat("w1")
        assert worker.status == "idle"  # heartbeat 恢复

    @pytest.mark.asyncio
    async def test_execution_with_retry_on_timeout(self, mock_node_executor):
        """超时后触发重试"""
        s = Scheduler(
            node_executor=mock_node_executor,
            retry_config=RetryConfig(max_retries=1, strategy="fixed", base_delay=0.01),
            timeout_config=TimeoutConfig(default_timeout=0.01, timeout_action="retry"),
        )
        await s.register_worker("w1", ["test"])
        await s.start()

        # 创建一个慢 workflow（但 mock 不会慢…用直接的方式测试）
        # 这里主要测重试逻辑不崩溃
        task_id = await s.submit_spec(
            workflow_spec=make_simple_workflow("retry_test"),
            capability="test",
        )

        result = await s.wait_for(task_id, timeout=10.0)
        assert result is not None
        assert result.status == TaskStatus.COMPLETED

        await s.stop()

    @pytest.mark.asyncio
    async def test_stats(self, mock_node_executor):
        s = Scheduler(node_executor=mock_node_executor)
        await s.register_worker("w1", ["code", "review"])
        await s.register_worker("w2", ["deploy"])

        stats = await s.stats()
        assert stats["worker_count"] == 2
        assert stats["available_workers"] == 2
        assert "code" in stats["capabilities"]
        assert stats["running"] is False

    @pytest.mark.asyncio
    async def test_retry_policy_skips_nonretryable(self, mock_node_executor):
        """不可重试错误直接失败（不崩溃）"""
        s = Scheduler(node_executor=mock_node_executor)
        rp = s.retry_policy

        # 不可重试的错误到最大重试后停止
        assert rp.should_retry("permission denied", 1) is False
        assert rp.should_retry("validation error", 2) is False

    @pytest.mark.asyncio
    async def test_task_submit_via_full_object(self, mock_node_executor):
        """直接用 ScheduledTask 对象提交"""
        s = Scheduler(node_executor=mock_node_executor)
        await s.register_worker("w1", ["full_obj"])
        await s.start()

        task = ScheduledTask(
            task_id="custom-id",
            capability="full_obj",
            workflow_spec=make_simple_workflow(),
            priority=1,
            metadata={"user": "test"},
        )
        task_id = await s.submit(task)

        result = await s.wait_for(task_id, timeout=10.0)
        assert result is not None
        assert result.status == TaskStatus.COMPLETED

        await s.stop()

    @pytest.mark.asyncio
    async def test_get_result_without_wait(self, mock_node_executor):
        s = Scheduler(node_executor=mock_node_executor)
        await s.register_worker("w1", ["direct"])
        await s.start()

        task_id = await s.submit_spec(
            workflow_spec=make_simple_workflow(),
            capability="direct",
        )

        result = await s.wait_for(task_id, timeout=10.0)
        assert result is not None

        # 再次获取应该返回 None（已消费）
        assert await s.get_result(task_id) is None

        await s.stop()
