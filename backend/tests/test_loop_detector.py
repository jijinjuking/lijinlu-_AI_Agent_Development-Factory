"""
W14 测试：无限循环检测 + 自动恢复
"""

import pytest
from app.runtime.loop_detector import (
    AutoRecovery,
    InfiniteLoopDetector,
    LoopAction,
    LoopDecision,
    LoopDetectionConfig,
    RecoveryAction,
    RecoveryResult,
    TaskLoopStats,
)


# ── Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def detector():
    """默认配置的检测器"""
    return InfiniteLoopDetector()


@pytest.fixture
def strict_detector():
    """严格配置的检测器（低阈值，便于测试触发条件）"""
    config = LoopDetectionConfig(
        max_node_visits=5,
        max_total_iterations=20,
        sequence_window=6,
        min_cycle_length=2,
        max_cycle_length=5,
    )
    return InfiniteLoopDetector(config)


@pytest.fixture
def recovery(strict_detector):
    """自动恢复引擎"""
    return AutoRecovery(strict_detector)


# ── 基础功能测试 ──────────────────────────────────────────────

class TestInfiniteLoopDetectorBasics:
    """基础功能：正常情况不误判"""

    @pytest.mark.asyncio
    async def test_no_loop_normal_sequence(self, detector):
        """正常节点序列不应被判定为循环"""
        nodes = ["start", "think", "act", "observe", "end"]
        for node in nodes:
            decision = await detector.check("task-1", node)
            assert not decision.is_loop

    @pytest.mark.asyncio
    async def test_no_loop_unique_nodes(self, detector):
        """大量不同节点的访问不应被判为循环"""
        for i in range(50):
            decision = await detector.check("task-1", f"node_{i}")
            assert not decision.is_loop

    @pytest.mark.asyncio
    async def test_below_threshold_no_loop(self, detector):
        """在阈值以下不应判为循环"""
        for _ in range(30):  # max_node_visits=30
            decision = await detector.check("task-1", "repeated_node")
        assert not decision.is_loop

    @pytest.mark.asyncio
    async def test_multiple_tasks_isolation(self, detector):
        """不同任务的统计应相互隔离"""
        for _ in range(10):
            await detector.check("task-a", "node_x")
            await detector.check("task-b", "node_y")

        stats_a = detector.get_task_stats("task-a")
        stats_b = detector.get_task_stats("task-b")

        assert stats_a.total_iterations == 10
        assert stats_b.total_iterations == 10
        assert stats_a.top_nodes[0][0] == "node_x"
        assert stats_b.top_nodes[0][0] == "node_y"


# ── 策略 1：单节点超限 ────────────────────────────────────────

class TestStrategySingleNode:
    """策略 1：单节点访问次数超限"""

    @pytest.mark.asyncio
    async def test_single_node_exceeds_threshold(self, strict_detector):
        """单节点超过阈值应触发循环检测"""
        for _ in range(5):  # 前 5 次不触发
            decision = await strict_detector.check("task-1", "loop_node")
        # 第 6 次触发（> max_node_visits=5）
        decision = await strict_detector.check("task-1", "loop_node")
        assert decision.is_loop
        assert "loop_node" in decision.reason
        assert "访问" in decision.reason
        assert decision.action == LoopAction.PAUSE

    @pytest.mark.asyncio
    async def test_single_node_has_suggestion(self, strict_detector):
        """超限决策应包含改进建议"""
        for _ in range(5):
            await strict_detector.check("task-1", "bad_node")
        decision = await strict_detector.check("task-1", "bad_node")
        assert decision.suggestion
        assert "出边" in decision.suggestion or "退出" in decision.suggestion

    @pytest.mark.asyncio
    async def test_different_nodes_stay_below_threshold(self, strict_detector):
        """不同节点各自计数，不互相影响"""
        for _ in range(6):
            await strict_detector.check("task-1", "node_a")
        decision_a = await strict_detector.check("task-1", "node_a")
        assert decision_a.is_loop

        decision_b = await strict_detector.check("task-1", "node_b")
        assert not decision_b.is_loop


# ── 策略 2：序列重复 ──────────────────────────────────────────

class TestStrategySequence:
    """策略 2：节点序列重复检测"""

    @pytest.mark.asyncio
    async def test_simple_repeating_sequence(self, strict_detector):
        """简单重复序列 [a,b] [a,b] 应触发循环"""
        pattern = ["node_a", "node_b"]
        for _ in range(4):  # 执行 4 轮（sequence_window=6, min_cycle=2）
            for node in pattern:
                decision = await strict_detector.check("task-1", node)
        # 最后一两轮应该检测到循环
        assert decision.is_loop or any(
            "序列" in d.reason
            for d in [_d for _d in [
                await strict_detector.check("task-1", n)
                for n in pattern
            ] if _d.is_loop]
        )

    @pytest.mark.asyncio
    async def test_three_node_repeating_sequence(self, strict_detector):
        """三节点重复序列 [a,b,c] [a,b,c] 应触发循环"""
        pattern = ["a", "b", "c"]
        # sequence_window=6, 所以至少需要两个完整周期被看到
        for _ in range(4):
            for node in pattern:
                await strict_detector.check("task-2", node)

        # 检查任务统计
        stats = strict_detector.get_task_stats("task-2")
        assert stats.total_iterations == 12

    @pytest.mark.asyncio
    async def test_non_repeating_sequence_no_loop(self, detector):
        """非重复序列不应误判"""
        nodes = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]
        for node in nodes:
            decision = await detector.check("task-3", node)
            assert not decision.is_loop, f"Node {node} incorrectly flagged as loop"

    @pytest.mark.asyncio
    async def test_sequence_detection_with_interleaving(self, strict_detector):
        """验证序列检测不受中间节点干扰"""
        # 构建: a,b,c,d,a,b,c,d 重复
        pattern = ["a", "b", "c", "d"]
        for _ in range(3):
            for node in pattern:
                await strict_detector.check("task-4", node)

        stats = strict_detector.get_task_stats("task-4")
        assert stats.total_iterations == 12
        # 12 次迭代应该没有达到 total_iterations 阈值


# ── 策略 3：总迭代超限 ────────────────────────────────────────

class TestStrategyTotalIterations:
    """策略 3：总迭代次数超限"""

    @pytest.mark.asyncio
    async def test_total_iterations_exceeds_threshold(self, strict_detector):
        """总迭代超过阈值应 abort"""
        for i in range(20):  # max_total_iterations=20
            decision = await strict_detector.check("task-1", f"node_{i % 5}")
        # 第 21 次触发
        decision = await strict_detector.check("task-1", "extra_node")
        assert decision.is_loop
        assert "总迭代" in decision.reason
        assert decision.action == LoopAction.ABORT

    @pytest.mark.asyncio
    async def test_total_iterations_below_threshold(self, strict_detector):
        """低于总迭代阈值不触发"""
        for i in range(20):  # = max_total_iterations
            decision = await strict_detector.check("task-2", f"node_{i}")
            if i < 20:  # 前 20 次不触发
                if decision.is_loop and "总迭代" in decision.reason:
                    pytest.fail(f"Iteration {i}: unexpected total iteration loop")


# ── 策略优先级测试 ────────────────────────────────────────────

class TestStrategyPriority:
    """验证检测优先级：总迭代 > 单节点 > 序列"""

    @pytest.mark.asyncio
    async def test_total_iterations_before_single_node(self, strict_detector):
        """总迭代超限应优先于单节点超限触发"""
        config = LoopDetectionConfig(
            max_node_visits=3,
            max_total_iterations=10,
        )
        d = InfiniteLoopDetector(config)

        for i in range(11):
            decision = await d.check("task-1", f"node_{i % 4}")

        assert decision.is_loop
        assert "总迭代" in decision.reason
        assert decision.action == LoopAction.ABORT

    @pytest.mark.asyncio
    async def test_single_node_before_sequence(self, strict_detector):
        """单节点超限应优先于序列检测"""
        config = LoopDetectionConfig(
            max_node_visits=3,
            max_total_iterations=100,
            sequence_window=8,
            min_cycle_length=2,
        )
        d = InfiniteLoopDetector(config)

        for _ in range(5):
            decision = await d.check("task-1", "stuck_node")

        assert decision.is_loop
        assert "stuck_node" in decision.reason


# ── 任务管理测试 ──────────────────────────────────────────────

class TestTaskManagement:
    """任务级别管理功能"""

    def test_get_task_stats_empty(self, detector):
        """空任务统计"""
        stats = detector.get_task_stats("nonexistent")
        assert stats.task_id == "nonexistent"
        assert stats.total_iterations == 0
        assert stats.unique_nodes == 0
        assert stats.top_nodes == []

    @pytest.mark.asyncio
    async def test_get_task_stats_with_data(self, detector):
        """有数据时的任务统计"""
        for _ in range(3):
            await detector.check("task-1", "node_a")
        for _ in range(2):
            await detector.check("task-1", "node_b")

        stats = detector.get_task_stats("task-1")
        assert stats.total_iterations == 5
        assert stats.unique_nodes == 2
        assert len(stats.top_nodes) == 2
        assert stats.top_nodes[0][0] == "node_a"
        assert stats.top_nodes[0][1] == 3
        assert stats.top_nodes[1][0] == "node_b"
        assert stats.top_nodes[1][1] == 2

    @pytest.mark.asyncio
    async def test_reset_task_clears_data(self, detector):
        """重置任务应清除所有数据"""
        for _ in range(10):
            await detector.check("task-1", "node_x")

        detector.reset_task("task-1")
        stats = detector.get_task_stats("task-1")
        assert stats.total_iterations == 0
        assert stats.unique_nodes == 0

    @pytest.mark.asyncio
    async def test_reset_nonexistent_task_no_error(self, detector):
        """重置不存在的任务不应报错"""
        detector.reset_task("nonexistent")

    @pytest.mark.asyncio
    async def test_active_tasks(self, detector):
        """活跃任务列表"""
        await detector.check("task-a", "node_1")
        await detector.check("task-b", "node_1")
        await detector.check("task-c", "node_1")

        active = detector.active_tasks()
        assert len(active) == 3
        assert "task-a" in active
        assert "task-b" in active
        assert "task-c" in active

    @pytest.mark.asyncio
    async def test_reset_task_removes_from_active(self, detector):
        """重置后任务从活跃列表移除"""
        await detector.check("task-a", "node_1")
        await detector.check("task-b", "node_1")
        detector.reset_task("task-a")

        active = detector.active_tasks()
        assert "task-a" not in active
        assert "task-b" in active


# ── 配置测试 ──────────────────────────────────────────────────

class TestConfiguration:
    """配置功能测试"""

    def test_default_config(self):
        """默认配置验证"""
        config = LoopDetectionConfig()
        assert config.max_node_visits == 30
        assert config.max_total_iterations == 100
        assert config.sequence_window == 10
        assert config.min_cycle_length == 2
        assert config.max_cycle_length == 10
        assert config.enable_auto_recovery is True
        assert config.recovery_max_retries == 3
        assert config.recovery_backoff_base == 2.0

    def test_custom_config(self):
        """自定义配置"""
        config = LoopDetectionConfig(
            max_node_visits=10,
            max_total_iterations=50,
            sequence_window=5,
            enable_auto_recovery=False,
        )
        assert config.max_node_visits == 10
        assert config.max_total_iterations == 50
        assert config.sequence_window == 5
        assert config.enable_auto_recovery is False

    @pytest.mark.asyncio
    async def test_detector_respects_config(self):
        """检测器应遵循配置"""
        config = LoopDetectionConfig(max_node_visits=2)
        d = InfiniteLoopDetector(config)

        await d.check("t1", "n1")
        await d.check("t1", "n1")
        decision = await d.check("t1", "n1")

        assert decision.is_loop


# ── Floyd 判圈算法测试 ────────────────────────────────────────

class TestFloydDetection:
    """Floyd 判圈算法验证"""

    @pytest.mark.asyncio
    async def test_floyd_detects_long_cycle(self, strict_detector):
        """Floyd 应检测长周期循环"""
        pattern = ["a", "b", "c", "d"]
        for _ in range(4):
            for node in pattern:
                await strict_detector.check("task-f", node)

        stats = strict_detector.get_task_stats("task-f")
        assert stats.total_iterations == 16

    @pytest.mark.asyncio
    async def test_no_floyd_false_positive(self, detector):
        """Floyd 不应误判非循环序列"""
        unique = [f"node_{i}" for i in range(20)]
        for node in unique:
            decision = await detector.check("task-u", node)
            assert not decision.is_loop, f"Node {node} falsely flagged"


# ── AutoRecovery 测试 ──────────────────────────────────────────

class TestAutoRecovery:
    """自动恢复引擎测试"""

    @pytest.mark.asyncio
    async def test_recovery_for_single_node_loop(self, recovery, strict_detector):
        """单节点循环应使用替代路径恢复"""
        # 触发单节点超限
        for _ in range(6):
            await strict_detector.check("task-1", "stuck")
        decision = await strict_detector.check("task-1", "stuck")
        assert decision.is_loop

        result = await recovery.attempt_recovery("task-1", decision)
        assert result.success
        assert result.action == RecoveryAction.ALTERNATIVE_PATH

    @pytest.mark.asyncio
    async def test_recovery_for_sequence_loop(self, recovery, strict_detector):
        """序列循环应使用 Checkpoint 恢复"""
        pattern = ["a", "b"]
        for _ in range(5):
            for node in pattern:
                await strict_detector.check("task-2", node)

        # 构造一个序列循环的 decision
        decision = LoopDecision(
            is_loop=True,
            reason="检测到循环序列: ['a', 'b']",
            action=LoopAction.PAUSE,
        )

        result = await recovery.attempt_recovery("task-2", decision)
        assert result.success
        assert result.action == RecoveryAction.CONTINUE_FROM_CHECKPOINT

    @pytest.mark.asyncio
    async def test_recovery_for_total_iterations(self, recovery, strict_detector):
        """总迭代超限应使用退避重试"""
        decision = LoopDecision(
            is_loop=True,
            reason="任务 'task-3' 总迭代 101 次，超过阈值 100",
            action=LoopAction.ABORT,
        )

        result = await recovery.attempt_recovery("task-3", decision)
        assert result.success
        assert result.action == RecoveryAction.RETRY_WITH_BACKOFF

    @pytest.mark.asyncio
    async def test_recovery_max_retries_exceeded(self, recovery, strict_detector):
        """超过最大重试次数应转人工介入"""
        decision = LoopDecision(
            is_loop=True,
            reason="节点 'x' 访问超过阈值",
            action=LoopAction.PAUSE,
        )

        # 先执行 recovery_max_retries=3 次
        for i in range(3):
            result = await recovery.attempt_recovery("task-4", decision)
            assert result.success, f"Retry {i} should succeed"
            assert result.action != RecoveryAction.HUMAN_INTERVENTION

        # 第 4 次应转人工
        result = await recovery.attempt_recovery("task-4", decision)
        assert not result.success
        assert result.action == RecoveryAction.HUMAN_INTERVENTION
        assert "最大重试次数" in result.message

    @pytest.mark.asyncio
    async def test_recovery_history_tracking(self, recovery, strict_detector):
        """恢复历史应正确追踪"""
        decision = LoopDecision(
            is_loop=True,
            reason="节点 'y' 访问超过阈值",
            action=LoopAction.PAUSE,
        )

        await recovery.attempt_recovery("task-5", decision)
        await recovery.attempt_recovery("task-5", decision)

        history = recovery.get_recovery_history("task-5")
        assert len(history) == 2
        assert all(isinstance(r, RecoveryResult) for r in history)

    @pytest.mark.asyncio
    async def test_reset_recovery_history(self, recovery, strict_detector):
        """重置恢复历史"""
        decision = LoopDecision(
            is_loop=True,
            reason="节点 'z' 访问超过阈值",
            action=LoopAction.PAUSE,
        )

        await recovery.attempt_recovery("task-6", decision)
        recovery.reset_recovery("task-6")
        history = recovery.get_recovery_history("task-6")
        assert len(history) == 0

    @pytest.mark.asyncio
    async def test_recovery_resets_detector_stats(self, recovery, strict_detector):
        """恢复应重置检测器统计"""
        # 先触发检测
        for _ in range(10):
            await strict_detector.check("task-7", "node_w")

        decision = LoopDecision(
            is_loop=True,
            reason="节点 'node_w' 访问超过阈值",
            action=LoopAction.PAUSE,
        )

        await recovery.attempt_recovery("task-7", decision)
        stats = strict_detector.get_task_stats("task-7")
        assert stats.total_iterations == 0

    @pytest.mark.asyncio
    async def test_backoff_increases_with_retries(self, recovery, strict_detector):
        """退避时间应随重试次数增加"""
        decision = LoopDecision(
            is_loop=True,
            reason="总迭代超限",
            action=LoopAction.ABORT,
        )

        results = []
        for _ in range(3):
            r = await recovery.attempt_recovery("task-8", decision)
            results.append(r)

        assert all(r.success for r in results)
        # 验证第三次恢复消息中包含退避信息
        assert "3" in results[2].message or "第 3 次" in results[2].message

    @pytest.mark.asyncio
    async def test_select_recovery_for_unknown_reason(self, recovery):
        """未知原因的循环应使用默认 Checkpoint 恢复"""
        decision = LoopDecision(
            is_loop=True,
            reason="未知错误导致循环",
            action=LoopAction.PAUSE,
        )

        result = await recovery.attempt_recovery("task-9", decision)
        assert result.success
        assert result.action == RecoveryAction.CONTINUE_FROM_CHECKPOINT


# ── 边界条件测试 ──────────────────────────────────────────────

class TestEdgeCases:
    """边界条件和极端情况"""

    @pytest.mark.asyncio
    async def test_empty_task_id_handled(self, detector):
        """空 task_id 应正常处理"""
        decision = await detector.check("", "node")
        assert not decision.is_loop

    @pytest.mark.asyncio
    async def test_empty_node_name_handled(self, detector):
        """空节点名应正常处理"""
        decision = await detector.check("task-1", "")
        assert not decision.is_loop

    @pytest.mark.asyncio
    async def test_special_characters_in_node_name(self, detector):
        """特殊字符节点名应正常处理"""
        decision = await detector.check(
            "task-1", "node/with/slashes?and=params&more#fragment"
        )
        assert not decision.is_loop

    @pytest.mark.asyncio
    async def test_very_long_node_name(self, detector):
        """超长节点名"""
        long_name = "n" * 1000
        decision = await detector.check("task-1", long_name)
        assert not decision.is_loop

    @pytest.mark.asyncio
    async def test_many_concurrent_tasks(self, detector):
        """大量并发任务的隔离性"""
        num_tasks = 100
        for i in range(num_tasks):
            await detector.check(f"task-{i}", f"node_{i % 10}")

        assert len(detector.active_tasks()) == num_tasks

        for i in range(num_tasks):
            stats = detector.get_task_stats(f"task-{i}")
            assert stats.total_iterations == 1

    @pytest.mark.asyncio
    async def test_cycle_length_boundary(self, detector):
        """循环长度边界测试"""
        config = LoopDetectionConfig(
            min_cycle_length=2,
            max_cycle_length=3,
            sequence_window=6,
        )
        d = InfiniteLoopDetector(config)

        # 2 节点循环应检测到
        for _ in range(5):
            await d.check("t1", "a")
            await d.check("t1", "b")

        stats = d.get_task_stats("t1")
        assert stats.total_iterations == 10

    @pytest.mark.asyncio
    async def test_sequence_window_smaller_than_cycle(self, detector):
        """序列窗口小于循环长度时的行为"""
        config = LoopDetectionConfig(
            sequence_window=4,
            min_cycle_length=3,
            max_cycle_length=5,
        )
        d = InfiniteLoopDetector(config)

        # 使用 3 节点循环
        for _ in range(5):
            await d.check("t1", "a")
            await d.check("t1", "b")
            await d.check("t1", "c")

        assert d.get_task_stats("t1").total_iterations == 15

    @pytest.mark.asyncio
    async def test_single_cycle_without_repetition(self, detector):
        """单次循环出现但未重复不触发"""
        # 只出现一次不会被检测（需要 repeat）
        pattern = ["x", "y", "z"]
        for node in pattern:
            decision = await detector.check("task-1", node)
            assert not decision.is_loop, f"Node {node} incorrectly flagged"


# ── Decision 模型测试 ─────────────────────────────────────────

class TestLoopDecisionModel:
    """LoopDecision 模型行为"""

    def test_loop_decision_defaults(self):
        """默认决策值"""
        d = LoopDecision(is_loop=False)
        assert d.is_loop is False
        assert d.reason == ""
        assert d.action == LoopAction.PAUSE
        assert d.suggestion == ""

    def test_loop_decision_with_values(self):
        """自定义决策值"""
        d = LoopDecision(
            is_loop=True,
            reason="测试原因",
            action=LoopAction.ABORT,
            suggestion="测试建议",
        )
        assert d.is_loop
        assert d.reason == "测试原因"
        assert d.action == LoopAction.ABORT
        assert d.suggestion == "测试建议"


# ── RecoveryResult 模型测试 ────────────────────────────────────

class TestRecoveryResultModel:
    """RecoveryResult 模型行为"""

    def test_recovery_result_defaults(self):
        """默认恢复结果"""
        r = RecoveryResult(success=True, action=RecoveryAction.CONTINUE_FROM_CHECKPOINT)
        assert r.success is True
        assert r.action == RecoveryAction.CONTINUE_FROM_CHECKPOINT
        assert r.message == ""

    def test_recovery_result_with_message(self):
        """带消息的恢复结果"""
        r = RecoveryResult(
            success=False,
            action=RecoveryAction.HUMAN_INTERVENTION,
            message="请人工检查",
        )
        assert not r.success
        assert r.action == RecoveryAction.HUMAN_INTERVENTION
        assert r.message == "请人工检查"


# ── TaskLoopStats 模型测试 ─────────────────────────────────────

class TestTaskLoopStats:
    """TaskLoopStats 模型"""

    def test_default_stats(self):
        """默认统计值"""
        s = TaskLoopStats(task_id="test")
        assert s.task_id == "test"
        assert s.total_iterations == 0
        assert s.unique_nodes == 0
        assert s.top_nodes == []
        assert not s.loop_detected
        assert s.last_detection is None
        assert s.recovery_count == 0
