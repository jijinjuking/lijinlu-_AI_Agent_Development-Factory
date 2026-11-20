"""
Policy Engine 测试套件

覆盖:
- TokenBudget
- CostControl
- PermissionEngine
- AuditLogger
- RetryPolicy
- TimeoutPolicy
- PolicyEngine（集成）
"""
import asyncio

import pytest

from app.runtime.policy_engine.models import (
    TokenBudgetConfig,
    TokenUsage,
    CostBudgetConfig,
    CostRecord,
    Permission,
    PermissionAction,
    PermissionResource,
    Role,
    AuditAction,
    AuditEntry,
    PolicyDecision,
    RetryConfig,
    TimeoutConfig,
)
from app.runtime.policy_engine.token_budget import TokenBudget
from app.runtime.policy_engine.cost_control import CostControl, MODEL_PRICING
from app.runtime.policy_engine.permission_engine import PermissionEngine, PRESET_ROLES
from app.runtime.policy_engine.audit_logger import AuditLogger
from app.runtime.policy_engine.retry_policy import RetryPolicy
from app.runtime.policy_engine.timeout_policy import TimeoutPolicy
from app.runtime.policy_engine.policy_engine import PolicyEngine


# ══════════════════════════════════════════════════════════════
# TokenBudget Tests
# ══════════════════════════════════════════════════════════════

class TestTokenBudget:
    """Token 配额管理测试"""

    def test_check_request_allow(self):
        """正常请求通过"""
        tb = TokenBudget()
        result = tb.check_request(1000, "task-1")
        assert result.allowed
        assert result.decision == PolicyDecision.ALLOW

    def test_check_request_exceeds_per_request(self):
        """超过单次请求上限"""
        config = TokenBudgetConfig(per_request_limit=500)
        tb = TokenBudget(config)
        result = tb.check_request(1000, "task-1")
        assert not result.allowed
        assert "per_request" in result.checks
        assert not result.checks["per_request"]

    def test_check_request_exceeds_per_task(self):
        """累计超过单任务上限"""
        tb = TokenBudget()
        # 逐步消耗任务配额
        tb.record_usage(TokenUsage(task_id="task-1", prompt_tokens=10000, completion_tokens=5000))
        assert tb.task_used("task-1") == 15000
        # 再次请求会超限
        result = tb.check_request(10000, "task-1")
        assert not result.allowed
        assert not result.checks["per_task"]

    def test_check_request_exceeds_daily_with_pause(self):
        """超过日配额触发暂停"""
        config = TokenBudgetConfig(daily_limit=10000, auto_pause=True, pause_threshold=0.95)
        tb = TokenBudget(config)
        tb.record_usage(TokenUsage(task_id="task-1", prompt_tokens=9500))
        result = tb.check_request(1000, "task-2")
        assert not result.allowed
        assert result.decision == PolicyDecision.PAUSE

    def test_check_request_warning_threshold(self):
        """超过警告阈值但不暂停"""
        config = TokenBudgetConfig(daily_limit=10000, warning_threshold=0.5, auto_pause=True,
                                   pause_threshold=0.95)
        tb = TokenBudget(config)
        tb.record_usage(TokenUsage(task_id="task-1", prompt_tokens=5000))
        result = tb.check_request(500, "task-2")
        assert result.allowed
        assert result.decision == PolicyDecision.WARN
        assert len(result.warnings) > 0

    def test_record_usage(self):
        """记录 Token 消耗"""
        tb = TokenBudget()
        tb.record_usage(TokenUsage(task_id="task-1", prompt_tokens=500, completion_tokens=300))
        assert tb.daily_used() == 800
        assert tb.task_used("task-1") == 800

    def test_record_usage_accumulates(self):
        """多次记录累计"""
        tb = TokenBudget()
        tb.record_usage(TokenUsage(task_id="task-1", prompt_tokens=100))
        tb.record_usage(TokenUsage(task_id="task-1", prompt_tokens=200))
        assert tb.task_used("task-1") == 300
        assert tb.daily_used() == 300

    def test_task_tracking_separate_tasks(self):
        """不同任务独立追踪"""
        tb = TokenBudget()
        tb.record_usage(TokenUsage(task_id="task-A", prompt_tokens=1000))
        tb.record_usage(TokenUsage(task_id="task-B", prompt_tokens=500))
        assert tb.task_used("task-A") == 1000
        assert tb.task_used("task-B") == 500
        assert tb.daily_used() == 1500

    def test_check_remaining(self):
        """查询剩余配额"""
        tb = TokenBudget(TokenBudgetConfig(daily_limit=10000, per_task_limit=5000))
        tb.record_usage(TokenUsage(task_id="task-1", prompt_tokens=3000))
        result = tb.check_remaining("task-1")
        assert result.allowed
        assert result.metadata["daily_pct"] == 0.3

    def test_check_remaining_pause(self):
        """配额用完触发暂停"""
        config = TokenBudgetConfig(daily_limit=1000, pause_threshold=0.5)
        tb = TokenBudget(config)
        tb.record_usage(TokenUsage(task_id="task-1", prompt_tokens=600))
        result = tb.check_remaining("task-1")
        assert not result.allowed
        assert result.decision == PolicyDecision.PAUSE

    def test_usage_history_filter(self):
        """按 task 过滤使用历史"""
        tb = TokenBudget()
        tb.record_usage(TokenUsage(task_id="task-A", prompt_tokens=100))
        tb.record_usage(TokenUsage(task_id="task-B", prompt_tokens=200))
        assert len(tb.usage_history("task-A")) == 1
        assert len(tb.usage_history()) == 2

    def test_reset_task(self):
        """重置单任务计数"""
        tb = TokenBudget()
        tb.record_usage(TokenUsage(task_id="task-1", prompt_tokens=500))
        tb.reset_task("task-1")
        assert tb.task_used("task-1") == 0

    def test_reset_all(self):
        """重置所有计数"""
        tb = TokenBudget()
        tb.record_usage(TokenUsage(task_id="task-1", prompt_tokens=500))
        tb.reset_all()
        assert tb.daily_used() == 0
        assert tb.task_used("task-1") == 0

    def test_daily_limit_getter(self):
        """配额配置 getter"""
        config = TokenBudgetConfig(daily_limit=50000, per_task_limit=10000)
        tb = TokenBudget(config)
        assert tb.daily_limit() == 50000
        assert tb.per_task_limit() == 10000


# ══════════════════════════════════════════════════════════════
# CostControl Tests
# ══════════════════════════════════════════════════════════════

class TestCostControl:
    """费用控制测试"""

    def test_calculate_cost_known_model(self):
        """已知模型费用计算"""
        cost = CostControl.calculate_cost("gpt-4o", 1000, 500)
        expected = 1000 / 1000 * 0.0025 + 500 / 1000 * 0.01
        assert cost == pytest.approx(expected)

    def test_calculate_cost_unknown_model(self):
        """未知模型用默认定价"""
        cost = CostControl.calculate_cost("my-model", 1000, 500)
        assert cost > 0

    def test_calculate_cost_qwen_free(self):
        """qwen2.5 本地免费"""
        cost = CostControl.calculate_cost("qwen2.5", 10000, 5000)
        assert cost == 0.0

    def test_check_budget_allow(self):
        """预算内通过"""
        cc = CostControl()
        result = cc.check_budget(0.01, "task-1")
        assert result.allowed

    def test_check_budget_exceeds_daily(self):
        """超过日预算"""
        config = CostBudgetConfig(daily_budget_usd=1.0, auto_pause=False)
        cc = CostControl(config)
        cc.record_cost(CostRecord(task_id="task-1", model="gpt-4o",
                                  prompt_tokens=500000, cost_usd=0.95))
        result = cc.check_budget(0.5, "task-2")
        assert not result.allowed
        assert not result.checks["daily"]

    def test_check_budget_exceeds_monthly(self):
        """超过月预算"""
        config = CostBudgetConfig(monthly_budget_usd=10.0, auto_pause=False)
        cc = CostControl(config)
        cc.record_cost(CostRecord(task_id="task-1", model="gpt-4o",
                                  prompt_tokens=0, cost_usd=9.5))
        result = cc.check_budget(1.0, "task-2")
        assert not result.allowed
        assert not result.checks["monthly"]

    def test_check_budget_warning(self):
        """超过警告阈值"""
        config = CostBudgetConfig(daily_budget_usd=10.0, warning_threshold=0.5)
        cc = CostControl(config)
        cc.record_cost(CostRecord(task_id="task-1", model="gpt-4o",
                                  prompt_tokens=0, cost_usd=5.0))
        result = cc.check_budget(0.5, "task-2")
        assert result.allowed
        assert result.decision == PolicyDecision.WARN

    def test_record_cost(self):
        """记录费用"""
        cc = CostControl()
        record = CostRecord(task_id="task-1", model="gpt-4o", cost_usd=0.05)
        cc.record_cost(record)
        assert cc.total_cost() == 0.05

    def test_record_call_convenience(self):
        """便捷记录方法"""
        cc = CostControl()
        record = cc.record_call("task-1", "gpt-4o", 1000, 500)
        assert record.cost_usd > 0
        assert cc.total_cost() == record.cost_usd

    def test_total_cost(self):
        """总费用"""
        cc = CostControl()
        cc.record_cost(CostRecord(task_id="task-1", model="a", cost_usd=1.0))
        cc.record_cost(CostRecord(task_id="task-2", model="b", cost_usd=2.0))
        assert cc.total_cost() == 3.0

    def test_cost_for_task(self):
        """按任务统计"""
        cc = CostControl()
        cc.record_cost(CostRecord(task_id="task-A", model="a", cost_usd=1.0))
        cc.record_cost(CostRecord(task_id="task-B", model="b", cost_usd=2.0))
        cc.record_cost(CostRecord(task_id="task-A", model="c", cost_usd=3.0))
        assert cc.cost_for_task("task-A") == 4.0

    def test_records_filter(self):
        """记录过滤"""
        cc = CostControl()
        cc.record_cost(CostRecord(task_id="task-A", model="a", cost_usd=1.0))
        cc.record_cost(CostRecord(task_id="task-B", model="b", cost_usd=2.0))
        assert len(cc.records("task-A")) == 1
        assert len(cc.records()) == 2

    def test_reset_all(self):
        """重置费用记录"""
        cc = CostControl()
        cc.record_cost(CostRecord(task_id="task-1", model="a", cost_usd=5.0))
        cc.reset_all()
        assert cc.total_cost() == 0.0


# ══════════════════════════════════════════════════════════════
# PermissionEngine Tests
# ══════════════════════════════════════════════════════════════

class TestPermissionEngine:
    """权限引擎测试"""

    def test_admin_has_all_access(self):
        """管理员可访问一切"""
        pe = PermissionEngine()
        result = pe.check(["admin"], PermissionAction.MANAGE, PermissionResource.POLICY)
        assert result.allowed

    def test_developer_can_execute_agent(self):
        """开发者可执行 Agent"""
        pe = PermissionEngine()
        result = pe.check(["developer"], PermissionAction.EXECUTE,
                          PermissionResource.AGENT, "my-agent")
        assert result.allowed

    def test_developer_cannot_manage_policy(self):
        """开发者不能管理策略"""
        pe = PermissionEngine()
        result = pe.check(["developer"], PermissionAction.MANAGE, PermissionResource.POLICY)
        assert not result.allowed

    def test_viewer_can_only_read(self):
        """观察者只能读"""
        pe = PermissionEngine()
        # 可以读
        assert pe.check(["viewer"], PermissionAction.READ, PermissionResource.AGENT).allowed
        # 不能写
        assert not pe.check(["viewer"], PermissionAction.WRITE, PermissionResource.AGENT).allowed
        # 不能执行
        assert not pe.check(["viewer"], PermissionAction.EXECUTE, PermissionResource.TOOL).allowed

    def test_viewer_cannot_write(self):
        """观察者不能写"""
        pe = PermissionEngine()
        result = pe.check(["viewer"], PermissionAction.WRITE, PermissionResource.AGENT)
        assert not result.allowed

    def test_explicit_deny(self):
        """显式 deny 覆盖 allow"""
        custom_role = Role(name="limited_dev", priority=50, permissions=[
            Permission(action=PermissionAction.EXECUTE, resource=PermissionResource.TOOL,
                       effect="allow"),
            Permission(action=PermissionAction.EXECUTE, resource=PermissionResource.TOOL,
                       resource_id="dangerous-tool", effect="deny"),
        ])
        pe = PermissionEngine({"limited_dev": custom_role})
        # 一般工具可以
        result = pe.check(["limited_dev"], PermissionAction.EXECUTE,
                          PermissionResource.TOOL, "safe-tool")
        assert result.allowed
        # 危险工具被拒绝
        result = pe.check(["limited_dev"], PermissionAction.EXECUTE,
                          PermissionResource.TOOL, "dangerous-tool")
        assert not result.allowed

    def test_unknown_role_denied(self):
        """未知角色被拒绝"""
        pe = PermissionEngine()
        result = pe.check(["nonexistent"], PermissionAction.READ, PermissionResource.AGENT)
        assert not result.allowed

    def test_precise_resource_id_match(self):
        """精确 resource_id 匹配"""
        custom_role = Role(name="dev", priority=50, permissions=[
            Permission(action=PermissionAction.EXECUTE, resource=PermissionResource.TOOL,
                       resource_id="specific-tool", effect="allow"),
        ])
        pe = PermissionEngine({"dev": custom_role})
        assert pe.check(["dev"], PermissionAction.EXECUTE,
                        PermissionResource.TOOL, "specific-tool").allowed
        assert not pe.check(["dev"], PermissionAction.EXECUTE,
                            PermissionResource.TOOL, "other-tool").allowed

    def test_can_execute_tool(self):
        """便捷方法：检查工具执行"""
        pe = PermissionEngine()
        assert pe.can_execute_tool(["developer"], "any-tool").allowed

    def test_can_run_agent(self):
        """便捷方法：检查 Agent 执行"""
        pe = PermissionEngine()
        assert pe.can_run_agent(["developer"], "any-agent").allowed

    def test_add_remove_role(self):
        """角色管理"""
        pe = PermissionEngine()
        custom_role = Role(name="custom", priority=30, permissions=[
            Permission(action=PermissionAction.READ, resource=PermissionResource.AGENT,
                       effect="allow"),
        ])
        pe.add_role(custom_role)
        assert pe.get_role("custom") is not None
        pe.remove_role("custom")
        assert pe.get_role("custom") is None

    def test_cannot_remove_preset_role(self):
        """不能删除预设角色"""
        pe = PermissionEngine()
        assert not pe.remove_role("admin")

    def test_list_roles_sorted(self):
        """角色按优先级排序"""
        pe = PermissionEngine()
        roles = pe.list_roles()
        priorities = [r.priority for r in roles]
        assert priorities == sorted(priorities, reverse=True)


# ══════════════════════════════════════════════════════════════
# AuditLogger Tests
# ══════════════════════════════════════════════════════════════

class TestAuditLogger:
    """审计日志测试"""

    def test_log_entry(self):
        """记录审计条目"""
        al = AuditLogger()
        al.log(AuditEntry(action=AuditAction.TASK_STARTED, task_id="task-1"))
        assert al.count == 1

    def test_log_action(self):
        """便捷记录方法"""
        al = AuditLogger()
        entry = al.log_action(AuditAction.TASK_COMPLETED, task_id="task-1", duration=5.0)
        assert entry.task_id == "task-1"
        assert entry.details["duration"] == 5.0

    def test_log_policy_violation(self):
        """记录策略违规"""
        al = AuditLogger()
        al.log_policy_violation("task-1", "budget exceeded", limit=100)
        assert al.violation_count() == 1

    def test_log_budget_exceeded(self):
        """记录预算超限"""
        al = AuditLogger()
        al.log_budget_exceeded("task-1", "token", 10000, 12000)
        entries = al.entries(action=AuditAction.BUDGET_EXCEEDED)
        assert len(entries) == 1
        assert entries[0].details["limit"] == 10000

    def test_log_permission_denied(self):
        """记录权限拒绝"""
        al = AuditLogger()
        al.log_permission_denied("task-1", "viewer", "write", "agent")
        assert al.count == 1

    def test_filter_by_task_id(self):
        """按任务过滤"""
        al = AuditLogger()
        al.log_action(AuditAction.TASK_STARTED, task_id="A")
        al.log_action(AuditAction.TASK_STARTED, task_id="B")
        assert len(al.entries(task_id="A")) == 1

    def test_filter_by_action(self):
        """按操作类型过滤"""
        al = AuditLogger()
        al.log_action(AuditAction.TASK_STARTED)
        al.log_action(AuditAction.TOOL_EXECUTED)
        assert len(al.entries(action=AuditAction.TOOL_EXECUTED)) == 1

    def test_violation_count(self):
        """违规计数"""
        al = AuditLogger()
        al.log_policy_violation("task-1", "err1")
        al.log_policy_violation("task-1", "err2")
        al.log_policy_violation("task-2", "err3")
        assert al.violation_count() == 3
        assert al.violation_count("task-1") == 2

    def test_recent_entries(self):
        """最近记录"""
        al = AuditLogger()
        for i in range(5):
            al.log_action(AuditAction.TASK_STARTED, task_id=f"task-{i}")
        recent = al.recent_entries(3)
        assert len(recent) == 3

    def test_clear(self):
        """清空审计日志"""
        al = AuditLogger()
        al.log_action(AuditAction.TASK_STARTED)
        al.clear()
        assert al.count == 0


# ══════════════════════════════════════════════════════════════
# RetryPolicy Tests
# ══════════════════════════════════════════════════════════════

class TestRetryPolicy:
    """重试策略测试"""

    def test_should_retry_within_limit(self):
        """重试次数内、可重试错误"""
        rp = RetryPolicy()
        assert rp.should_retry("connection_error occurred", 1)

    def test_should_not_retry_exceeded(self):
        """超过最大重试次数"""
        config = RetryConfig(max_retries=2)
        rp = RetryPolicy(config)
        assert not rp.should_retry("timeout", 2)

    def test_should_not_retry_non_retryable(self):
        """非可重试错误"""
        rp = RetryPolicy()
        assert not rp.should_retry("permission denied", 0)

    def test_delay_exponential(self):
        """指数退避"""
        config = RetryConfig(strategy="exponential", base_delay=2.0, max_delay=100)
        rp = RetryPolicy(config)
        assert rp.delay_seconds(1) == 2.0   # 2 * 2^0
        assert rp.delay_seconds(2) == 4.0   # 2 * 2^1
        assert rp.delay_seconds(3) == 8.0   # 2 * 2^2
        assert rp.delay_seconds(10) == 100  # capped

    def test_delay_linear(self):
        """线性递增"""
        config = RetryConfig(strategy="linear", base_delay=1.0)
        rp = RetryPolicy(config)
        assert rp.delay_seconds(1) == 1.0
        assert rp.delay_seconds(3) == 3.0

    def test_delay_fixed(self):
        """固定间隔"""
        config = RetryConfig(strategy="fixed", base_delay=5.0)
        rp = RetryPolicy(config)
        assert rp.delay_seconds(1) == 5.0
        assert rp.delay_seconds(5) == 5.0

    @pytest.mark.asyncio
    async def test_backoff_returns_delay(self):
        """退避等待返回秒数"""
        rp = RetryPolicy(RetryConfig(base_delay=0.01))
        delay = await rp.backoff(1, "timeout")
        assert delay == 0.01


# ══════════════════════════════════════════════════════════════
# TimeoutPolicy Tests
# ══════════════════════════════════════════════════════════════

class TestTimeoutPolicy:
    """超时策略测试"""

    def test_timeout_seconds_default(self):
        """默认超时"""
        tp = TimeoutPolicy()
        assert tp.timeout_seconds("any_capability") == 300.0

    def test_timeout_seconds_per_capability(self):
        """按能力超时"""
        config = TimeoutConfig(default_timeout=60, per_capability={"browser_control": 120})
        tp = TimeoutPolicy(config)
        assert tp.timeout_seconds("code_generation") == 60
        assert tp.timeout_seconds("browser_control") == 120

    def test_timeout_action(self):
        """超时动作"""
        tp = TimeoutPolicy()
        assert tp.timeout_action == "cancel"

    @pytest.mark.asyncio
    async def test_with_timeout_completes(self):
        """正常完成"""
        tp = TimeoutPolicy(TimeoutConfig(default_timeout=5.0))

        async def fast_task():
            await asyncio.sleep(0.01)
            return "done"

        result, timed_out, error = await tp.with_timeout(fast_task, "test")
        assert result == "done"
        assert not timed_out
        assert error is None

    @pytest.mark.asyncio
    async def test_with_timeout_times_out(self):
        """超时"""
        tp = TimeoutPolicy(TimeoutConfig(default_timeout=0.01))

        async def slow_task():
            await asyncio.sleep(10)
            return "never"

        result, timed_out, error = await tp.with_timeout(slow_task, "test")
        assert result is None
        assert timed_out


# ══════════════════════════════════════════════════════════════
# PolicyEngine Integration Tests
# ══════════════════════════════════════════════════════════════

class TestPolicyEngine:
    """策略引擎集成测试"""

    def test_check_all_pass(self):
        """全部检查通过"""
        pe = PolicyEngine()
        result = pe.check(
            task_id="task-1",
            role_names=["developer"],
            action=PermissionAction.EXECUTE,
            resource=PermissionResource.AGENT,
            estimated_tokens=100,
        )
        assert result.allowed

    def test_check_permission_denied(self):
        """权限拒绝 → 整体拒绝"""
        pe = PolicyEngine()
        result = pe.check(
            task_id="task-1",
            role_names=["viewer"],
            action=PermissionAction.WRITE,
            resource=PermissionResource.AGENT,
            estimated_tokens=100,
        )
        assert not result.allowed
        assert not result.checks["permission"]
        # 审计日志记录了拒绝
        assert pe.audit.violation_count() == 1

    def test_check_token_exceeded(self):
        """Token 超限"""
        config = TokenBudgetConfig(daily_limit=1000, auto_pause=False)
        pe = PolicyEngine(token_config=config)
        pe.token_budget.record_usage(
            TokenUsage(task_id="task-1", prompt_tokens=900))
        result = pe.check(
            task_id="task-2",
            role_names=["developer"],
            action=PermissionAction.EXECUTE,
            resource=PermissionResource.AGENT,
            estimated_tokens=500,
        )
        assert not result.allowed
        assert not result.checks["token_budget"]

    def test_check_cost_exceeded(self):
        """费用超限"""
        cost_config = CostBudgetConfig(daily_budget_usd=0.05, auto_pause=False)
        pe = PolicyEngine(cost_config=cost_config)
        pe.cost_control.record_call("task-1", "gpt-4o", 20000, 0)  # ~$0.05
        result = pe.check(
            task_id="task-2",
            role_names=["developer"],
            action=PermissionAction.EXECUTE,
            resource=PermissionResource.AGENT,
            estimated_tokens=10000,
            model="gpt-4o",
        )
        assert not result.allowed
        assert not result.checks["cost_budget"]

    def test_check_permission_only(self):
        """只检查权限"""
        pe = PolicyEngine()
        result = pe.check_permission_only(
            ["admin"], PermissionAction.MANAGE, PermissionResource.POLICY)
        assert result.allowed

    def test_check_budget_only(self):
        """只检查预算"""
        pe = PolicyEngine()
        result = pe.check_budget_only("task-1", estimated_tokens=100, model="gpt-4o")
        assert result.allowed

    def test_record_token_usage(self):
        """记录 Token 消耗"""
        pe = PolicyEngine()
        usage = TokenUsage(task_id="task-1", prompt_tokens=500, completion_tokens=300)
        pe.record_token_usage(usage)
        assert pe.token_budget.daily_used() == 800
        assert pe.audit.count >= 1  # 审计记录了 TOOL_EXECUTED

    def test_stats(self):
        """引擎统计"""
        pe = PolicyEngine()
        pe.record_token_usage(TokenUsage(task_id="task-1", prompt_tokens=1000))
        stats = pe.stats()
        assert "token" in stats
        assert "cost" in stats
        assert "audit" in stats
        assert stats["token"]["daily_used"] == 1000

    def test_chain_accumulation(self):
        """链条累积效果"""
        pe = PolicyEngine()
        # 多次请求累加
        for _ in range(5):
            pe.record_token_usage(TokenUsage(task_id="task-1", prompt_tokens=1000))
        assert pe.token_budget.task_used("task-1") == 5000
        assert pe.audit.count == 5

    def test_reset_all(self):
        """重置所有状态"""
        pe = PolicyEngine()
        pe.record_token_usage(TokenUsage(task_id="task-1", prompt_tokens=1000))
        pe.audit.log_policy_violation("task-1", "test")
        pe.reset_all()
        assert pe.token_budget.daily_used() == 0
        assert pe.audit.count == 0

    def test_retry_policy(self):
        """策略引擎中的重试策略"""
        pe = PolicyEngine()
        assert pe.retry.should_retry("timeout", 0)

    def test_timeout_policy(self):
        """策略引擎中的超时策略"""
        pe = PolicyEngine()
        assert pe.timeout.timeout_seconds("test") == 300.0


# ══════════════════════════════════════════════════════════════
# Model Configuration Tests
# ══════════════════════════════════════════════════════════════

class TestModelPricing:
    """模型定价表测试"""

    def test_pricing_table_has_entries(self):
        """定价表非空"""
        assert len(MODEL_PRICING) > 0

    def test_pricing_table_has_unknown_fallback(self):
        """unknown 回退存在"""
        assert "unknown" in MODEL_PRICING

    def test_preset_roles_complete(self):
        """预设角色包含三种"""
        assert set(PRESET_ROLES.keys()) == {"admin", "developer", "viewer"}
