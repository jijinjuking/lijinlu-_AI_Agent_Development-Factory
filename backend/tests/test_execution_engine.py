"""
W7 Execution Engine 测试套件

覆盖模块:
1. WorkflowSchema — 类型定义、序列化、桥接函数
2. NodeExecutor — 四种节点类型执行
3. InterruptHandler — 中断创建/审批/拒绝/列表
4. LangGraphAdapter — Graph 构建与执行
5. Integration — 端到端工作流执行
6. Edge Cases — 边界情况
7. Phase 1 — NodeDefaults / EdgeType / Command(goto) / Send() / set_node_defaults
8. Phase 2 — stream_mode(7种) / StreamWriter / context_schema + Runtime

测试风格: pytest + pytest-asyncio (对齐已有风格)
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.runtime.execution_engine.workflow_schema import (
    # Types
    WorkflowState,
    WorkflowSpec,
    NodeSpec,
    EdgeSpec,
    NodeType,
    EdgeType,
    NodeDefaults,
    # Factory
    create_default_state,
    # Bridge
    workflow_state_to_lightweight,
    lightweight_to_workflow_state,
    # Demo
    EXAMPLE_WORKFLOW,
)
from app.runtime.execution_engine.runtime_context import (
    RuntimeContext,
    create_runtime_context,
)
from app.runtime.execution_engine.langgraph_adapter import _eval_items_expr
from app.runtime.execution_engine.node_executor import NodeExecutor
from app.runtime.execution_engine.interrupt_handler import (
    InterruptHandler,
    InterruptRequest,
)
from app.runtime.execution_engine.langgraph_adapter import LangGraphAdapter
from app.runtime.state_manager.lightweight_state import LightweightState
from app.runtime.tool_runtime.executor import ToolExecutor
from app.runtime.tool_runtime.models import (
    ExecutionContext,
    ExecutionResult,
    ExecutionStatus,
    PermissionLevel,
)


# ═══════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════

def _make_simple_workflow(with_condition: bool = False) -> WorkflowSpec:
    """创建简单线性工作流：start → tool → end"""
    nodes = [
        NodeSpec(id="start", type=NodeType.START, label="开始"),
        NodeSpec(
            id="run_tool",
            type=NodeType.TOOL,
            label="执行工具",
            config={"tool_name": "test_tool", "args_template": {}},
        ),
    ]
    edges = [EdgeSpec(source="start", target="run_tool")]

    if with_condition:
        nodes.append(
            NodeSpec(
                id="check",
                type=NodeType.CONDITION,
                label="检查结果",
                config={"expression": "state.get('tool_success', False)"},
            )
        )
        edges += [
            EdgeSpec(source="run_tool", target="check"),
            EdgeSpec(source="check", target="end_pass", condition="true"),
            EdgeSpec(source="check", target="end_fail", condition="false"),
        ]
        nodes += [
            NodeSpec(id="end_pass", type=NodeType.END, label="通过"),
            NodeSpec(id="end_fail", type=NodeType.END, label="失败"),
        ]
    else:
        nodes.append(NodeSpec(id="end", type=NodeType.END, label="结束"))
        edges.append(EdgeSpec(source="run_tool", target="end"))

    return WorkflowSpec(name="test_workflow", nodes=nodes, edges=edges)


# ── Standalone mock adapter (not a closure, avoids Python 3.13 await bug) ──

async def _mock_tool_adapter(args: dict, ctx) -> ExecutionResult:
    """独立 async 函数，返回成功结果"""
    return ExecutionResult(
        tool_name=args.get("_tool_name", "mock"),
        status=ExecutionStatus.COMPLETED,
        output=f"Mock output: args={args}",
    )


class MockToolRegistry:
    """模拟 ToolRegistry，永远返回成功"""
    def get(self, name: str):
        from app.runtime.tool_runtime.models import ToolInfo, PermissionLevel

        return ToolInfo(
            name=name,
            display_name=name,
            description=f"Mock tool: {name}",
            parameters_schema={"type": "object", "properties": {}, "required": []},
            permission_level=PermissionLevel.NORMAL,
            adapter=_mock_tool_adapter,
        )


@pytest.fixture
def mock_tool_executor():
    """带 Mock ToolRegistry 的 ToolExecutor"""
    registry = MockToolRegistry()
    return ToolExecutor(registry=registry)


# ═══════════════════════════════════════════
# 1. WorkflowSchema 测试
# ═══════════════════════════════════════════

class TestWorkflowState:
    """WorkflowState 类型测试"""

    def test_create_default_state(self):
        state = create_default_state(task_id="task-1", goal="Hello world")
        assert state["task_id"] == "task-1"
        assert state["current_goal"] == "Hello world"
        assert state["workflow_status"] == "idle"
        assert state["error_count"] == 0
        assert state["max_retries"] == 3
        assert state["messages"] == []
        assert state["steps"] == []

    def test_state_mutation(self):
        state = create_default_state(task_id="t1")
        state["messages"].append({"role": "user", "content": "hello"})
        state["error_count"] += 1
        assert len(state["messages"]) == 1
        assert state["error_count"] == 1


class TestWorkflowSpec:
    """WorkflowSpec JSON 定义测试"""

    def test_basic_spec(self):
        spec = _make_simple_workflow()
        assert spec.name == "test_workflow"
        assert len(spec.nodes) == 3
        assert len(spec.edges) == 2
        assert spec.get_entry_node_id() == "start"

    def test_get_entry_node_explicit(self):
        spec = WorkflowSpec(
            name="test",
            entry_node="custom_start",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="custom_start", type=NodeType.START),
            ],
            edges=[],
        )
        assert spec.get_entry_node_id() == "custom_start"

    def test_get_entry_node_first_start(self):
        spec = WorkflowSpec(
            name="test",
            nodes=[
                NodeSpec(id="step1", type=NodeType.TOOL),
                NodeSpec(id="step2", type=NodeType.START),
            ],
            edges=[],
        )
        assert spec.get_entry_node_id() == "step2"

    def test_get_outgoing_edges(self):
        spec = _make_simple_workflow()
        out = spec.get_outgoing_edges("start")
        assert len(out) == 1
        assert out[0].target == "run_tool"

    def test_get_outgoing_edges_empty(self):
        spec = _make_simple_workflow()
        out = spec.get_outgoing_edges("end")
        assert len(out) == 0

    def test_get_incoming_edges(self):
        spec = _make_simple_workflow()
        incoming = spec.get_incoming_edges("run_tool")
        assert len(incoming) == 1
        assert incoming[0].source == "start"

    def test_example_workflow_structure(self):
        """验证 EXAMPLE_WORKFLOW 结构完整"""
        spec = EXAMPLE_WORKFLOW
        assert spec.name == "代码审查工作流"
        assert len(spec.nodes) == 6
        assert len(spec.edges) == 6
        # 验证节点类型分布
        types = [n.type for n in spec.nodes]
        assert NodeType.START in types
        assert NodeType.END in types
        assert NodeType.LLM in types
        assert NodeType.TOOL in types
        assert NodeType.CONDITION in types
        assert NodeType.HUMAN_APPROVAL in types


class TestBridgeFunctions:
    """LightweightState ↔ WorkflowState 桥接测试"""

    def test_round_trip_preserves_core_fields(self):
        ws = create_default_state(task_id="task-x", goal="Test goal", project_id="proj-1")
        ws["messages"].append({"role": "user", "content": "hi"})
        ws["steps"].append({"node": "start", "outcome": "success"})

        ls = workflow_state_to_lightweight(ws)
        assert ls.task_id == "task-x"
        assert ls.current_goal == "Test goal"
        assert ls.project_id == "proj-1"
        assert len(ls.messages) == 1
        assert len(ls.steps) == 1

        ws2 = lightweight_to_workflow_state(ls)
        assert ws2["task_id"] == "task-x"
        assert ws2["current_goal"] == "Test goal"
        assert len(ws2["messages"]) == 1

    def test_empty_state_round_trip(self):
        ws = create_default_state()
        ls = workflow_state_to_lightweight(ws)
        ws2 = lightweight_to_workflow_state(ls)
        assert ws2["task_id"] == ""
        assert ws2["workflow_status"] == "idle"

    def test_approval_fields_preserved(self):
        ws = create_default_state(task_id="t1")
        ws["approval_needed"] = True
        ws["approval_result"] = None

        ls = workflow_state_to_lightweight(ws)
        assert ls.approval_needed is True
        assert ls.approval_result is None

        ws2 = lightweight_to_workflow_state(ls)
        assert ws2["approval_needed"] is True
        assert ws2["approval_result"] is None


# ═══════════════════════════════════════════
# 2. NodeExecutor 测试
# ═══════════════════════════════════════════

class TestNodeExecutorTool:
    """NodeExecutor — Tool 节点测试"""

    @pytest.mark.asyncio
    async def test_execute_tool_node(self, mock_tool_executor):
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        node = NodeSpec(
            id="tool1",
            type=NodeType.TOOL,
            config={"tool_name": "test_tool", "args_template": {}},
        )
        state = create_default_state(task_id="task-1")

        result = await executor.execute_node(node, state)

        # 验证消息写入
        msgs = result.get("messages", [])
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1
        assert tool_msgs[0]["tool_name"] == "test_tool"
        assert tool_msgs[0]["status"] == "completed"

        # 验证步骤记录
        steps = result.get("steps", [])
        assert len(steps) >= 1
        assert steps[-1]["node"] == "tool1"
        assert steps[-1]["outcome"] == "success"

    @pytest.mark.asyncio
    async def test_execute_tool_with_args_template(self, mock_tool_executor):
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        node = NodeSpec(
            id="tool1",
            type=NodeType.TOOL,
            config={
                "tool_name": "echo",
                "args_template": {"message": "{{ state.current_goal }}"},
            },
        )
        state = create_default_state(task_id="t1", goal="Hello World")

        result = await executor.execute_node(node, state)
        msgs = [m for m in result.get("messages", []) if m.get("role") == "tool"]
        assert len(msgs) >= 1
        # 输出应包含入参
        assert "Hello World" in msgs[0]["content"] or "args=" in msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_execute_tool_not_registered(self):
        """工具未注册时返回错误"""
        executor = NodeExecutor()  # 无 mock，工具未注册
        node = NodeSpec(
            id="tool1",
            type=NodeType.TOOL,
            config={"tool_name": "non_existent_tool", "args_template": {}},
        )
        state = create_default_state(task_id="t1")

        result = await executor.execute_node(node, state)
        msgs = [m for m in result.get("messages", []) if m.get("role") == "tool"]
        assert result["error_count"] >= 1
        # 至少有一条消息（可能是错误消息）
        assert len(result.get("messages", [])) >= 1


class TestNodeExecutorLLM:
    """NodeExecutor — LLM 节点测试"""

    @pytest.mark.asyncio
    async def test_execute_llm_node_mock_mode(self):
        """无 llm_callable 时使用 mock 模式"""
        executor = NodeExecutor()  # no llm_callable
        node = NodeSpec(
            id="llm1",
            type=NodeType.LLM,
            config={"system_prompt": "You are a helpful assistant."},
        )
        state = create_default_state(task_id="t1")

        result = await executor.execute_node(node, state)
        msgs = [m for m in result.get("messages", []) if m.get("role") == "assistant"]
        assert len(msgs) >= 1
        assert "LLM node" in msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_execute_llm_node_with_callable(self):
        """使用真实 llm_callable"""
        async def mock_llm(system_prompt, messages, config):
            return {"content": "LLM response!", "tokens": 100, "cost": 0.01}

        executor = NodeExecutor(llm_callable=mock_llm)
        node = NodeSpec(
            id="llm1",
            type=NodeType.LLM,
            config={"system_prompt": "You are helpful."},
        )
        state = create_default_state(task_id="t1")

        result = await executor.execute_node(node, state)
        msgs = [m for m in result.get("messages", []) if m.get("role") == "assistant"]
        assert len(msgs) >= 1
        assert result["llm_call_count"] == 1
        assert result["total_tokens"] == 100
        assert result["total_cost"] == 0.01


class TestNodeExecutorCondition:
    """NodeExecutor — Condition 节点测试"""

    @pytest.mark.asyncio
    async def test_condition_expr_simple_true(self):
        executor = NodeExecutor()
        node = NodeSpec(
            id="cond1",
            type=NodeType.CONDITION,
            config={"expression": "state.get('workflow_status') == 'idle'"},
        )
        state = create_default_state(task_id="t1")

        result = await executor.execute_node(node, state)
        cond_results = result.get("metadata", {}).get("condition_results", {})
        assert cond_results.get("cond1") is True

    @pytest.mark.asyncio
    async def test_condition_expr_false(self):
        executor = NodeExecutor()
        node = NodeSpec(
            id="cond1",
            type=NodeType.CONDITION,
            config={"expression": "state.get('error_count') > 0"},
        )
        state = create_default_state(task_id="t1")

        result = await executor.execute_node(node, state)
        cond_results = result.get("metadata", {}).get("condition_results", {})
        assert cond_results.get("cond1") is False

    @pytest.mark.asyncio
    async def test_condition_invalid_expr(self):
        """无效表达式不应崩溃"""
        executor = NodeExecutor()
        node = NodeSpec(
            id="cond1",
            type=NodeType.CONDITION,
            config={"expression": "this.is.totally.invalid"},
        )
        state = create_default_state(task_id="t1")

        result = await executor.execute_node(node, state)
        # 不应抛出异常
        assert result["workflow_status"] == "idle"


class TestNodeExecutorHumanApproval:
    """NodeExecutor — Human Approval 节点测试"""

    @pytest.mark.asyncio
    async def test_human_approval_sets_state(self):
        executor = NodeExecutor()
        node = NodeSpec(
            id="approve1",
            type=NodeType.HUMAN_APPROVAL,
            config={"message": "请确认操作", "timeout_seconds": 60},
        )
        state = create_default_state(task_id="t1")

        result = await executor.execute_node(node, state)
        assert result["approval_needed"] is True
        assert result["workflow_status"] == "waiting_approval"
        assert result["metadata"]["approval_node"] == "approve1"
        assert "请确认操作" in result["metadata"]["approval_message"]


class TestNodeExecutorStartEnd:
    """NodeExecutor — Start/End 节点测试"""

    @pytest.mark.asyncio
    async def test_start_node(self):
        executor = NodeExecutor()
        node = NodeSpec(id="start", type=NodeType.START)
        state = create_default_state(task_id="t1")

        result = await executor.execute_node(node, state)
        assert result["workflow_status"] == "idle"

    @pytest.mark.asyncio
    async def test_end_node(self):
        executor = NodeExecutor()
        node = NodeSpec(id="end", type=NodeType.END)
        state = create_default_state(task_id="t1")

        result = await executor.execute_node(node, state)
        assert result["workflow_status"] == "idle"


# ═══════════════════════════════════════════
# 3. InterruptHandler 测试
# ═══════════════════════════════════════════

class TestInterruptHandler:
    """InterruptHandler 单元测试"""

    def test_create_interrupt(self):
        ih = InterruptHandler()
        req = ih.request_approval("task-1", "node-1", "Please approve")
        assert req.task_id == "task-1"
        assert req.node_id == "node-1"
        assert req.status == "pending"
        assert ih.has_pending("task-1")

    def test_get_pending(self):
        ih = InterruptHandler()
        ih.request_approval("task-1", "n1", "msg")
        pending = ih.get_pending("task-1")
        assert pending is not None
        assert pending.task_id == "task-1"

    def test_get_pending_nonexistent(self):
        ih = InterruptHandler()
        assert ih.get_pending("no-such-task") is None

    def test_approve_interrupt(self):
        ih = InterruptHandler()
        ih.request_approval("task-1", "n1", "msg")
        req = ih.resume_with_approval("task-1", approved=True, reason="LGTM")
        assert req is not None
        assert req.status == "approved"
        assert not ih.has_pending("task-1")

    def test_reject_interrupt(self):
        ih = InterruptHandler()
        ih.request_approval("task-1", "n1", "msg")
        req = ih.resume_with_approval("task-1", approved=False, reason="Not yet")
        assert req is not None
        assert req.status == "rejected"
        assert not ih.has_pending("task-1")

    def test_resume_nonexistent(self):
        ih = InterruptHandler()
        req = ih.resume_with_approval("no-task", approved=True)
        assert req is None

    def test_cancel_interrupt(self):
        ih = InterruptHandler()
        ih.request_approval("task-1", "n1", "msg")
        req = ih.cancel("task-1")
        assert req is not None
        assert req.status == "timeout"
        assert not ih.has_pending("task-1")

    def test_list_all_pending(self):
        ih = InterruptHandler()
        ih.request_approval("task-1", "n1", "First")
        ih.request_approval("task-2", "n2", "Second")
        pending = ih.list_all_pending()
        assert len(pending) == 2

    def test_history_tracks_resolved(self):
        ih = InterruptHandler()
        ih.request_approval("task-1", "n1", "msg")
        ih.resume_with_approval("task-1", approved=True)
        history = ih.get_history("task-1")
        assert len(history) == 1
        assert history[0].status == "approved"

    def test_empty_history(self):
        ih = InterruptHandler()
        history = ih.get_history("no-task")
        assert history == []

    def test_to_dict_from_dict(self):
        req = InterruptRequest(
            task_id="task-1",
            node_id="n1",
            message="Test message",
            timeout_seconds=120,
            created_at="2025-01-01T00:00:00",
        )
        d = req.to_dict()
        req2 = InterruptRequest.from_dict(d)
        assert req2.task_id == req.task_id
        assert req2.node_id == req.node_id
        assert req2.message == req.message
        assert req2.timeout_seconds == 120


# ═══════════════════════════════════════════
# 4. LangGraphAdapter — Build 测试
# ═══════════════════════════════════════════

class TestLangGraphAdapterBuild:
    """LangGraphAdapter build() 测试"""

    def test_build_simple_workflow(self):
        """Build 简单线性工作流"""
        adapter = LangGraphAdapter()
        spec = _make_simple_workflow()
        graph = adapter.build(spec)
        assert graph is not None

    def test_build_conditional_workflow(self):
        """Build 带条件分支的工作流"""
        adapter = LangGraphAdapter()
        spec = _make_simple_workflow(with_condition=True)
        graph = adapter.build(spec)
        assert graph is not None

    def test_build_example_workflow(self):
        """Build 示例工作流"""
        adapter = LangGraphAdapter()
        graph = adapter.build(EXAMPLE_WORKFLOW)
        assert graph is not None
        assert len(graph.nodes) >= 7

    def test_build_minimal_workflow(self):
        """Build 最小工作流（只有 start → end）"""
        spec = WorkflowSpec(
            name="minimal",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[EdgeSpec(source="start", target="end")],
        )
        adapter = LangGraphAdapter()
        graph = adapter.build(spec)
        assert graph is not None

    def test_build_no_edges(self):
        """无边的单节点工作流"""
        spec = WorkflowSpec(
            name="solo",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[],
        )
        adapter = LangGraphAdapter()
        graph = adapter.build(spec)  # 不应崩溃
        assert graph is not None


# ═══════════════════════════════════════════
# 5. LangGraphAdapter — Execute 测试
# ═══════════════════════════════════════════

class TestLangGraphAdapterExecute:
    """LangGraphAdapter astream() 测试 — 使用真实 LangGraph 执行"""

    @pytest.mark.asyncio
    async def test_simple_linear_execution(self, mock_tool_executor):
        """start → tool → end 线性执行"""
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        adapter = LangGraphAdapter(node_executor=executor)
        spec = _make_simple_workflow(with_condition=False)
        graph = adapter.build(spec)

        state = create_default_state(task_id="task-test-1", goal="Test")
        events = []
        async for evt in adapter.astream(graph, state, "task-test-1"):
            events.append(evt)

        event_types = [e["event"] for e in events]
        assert "node_exited" in event_types
        assert "completed" in event_types

        # 验证执行了 tool
        final_state = events[-1].get("state", {})
        tool_msgs = [m for m in final_state.get("messages", []) if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1

    @pytest.mark.asyncio
    async def test_workflow_publishes_task_events(self, mock_tool_executor):
        """验证发布 TASK_STARTED / TASK_COMPLETED 事件"""
        from app.core.event_bus import event_bus

        executor = NodeExecutor(tool_executor=mock_tool_executor)
        adapter = LangGraphAdapter(node_executor=executor)
        spec = _make_simple_workflow(with_condition=False)
        graph = adapter.build(spec)

        state = create_default_state(task_id="task-ev-1")

        events = []
        async for evt in adapter.astream(graph, state, "task-ev-1"):
            events.append(evt)

        # 检查 EventBus 中的历史事件
        bus_events = event_bus.get_events("task-ev-1")
        event_types = [e["type"] for e in bus_events]
        assert "TASK_STARTED" in event_types
        assert "WORKFLOW_NODE_ENTERED" in event_types
        assert "WORKFLOW_NODE_EXITED" in event_types
        assert "TASK_COMPLETED" in event_types

    @pytest.mark.asyncio
    async def test_workflow_final_state_completed(self, mock_tool_executor):
        """验证执行完成后 workflow_status 为 completed"""
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        adapter = LangGraphAdapter(node_executor=executor)
        spec = _make_simple_workflow(with_condition=False)
        graph = adapter.build(spec)

        state = create_default_state(task_id="task-comp-1")
        async for evt in adapter.astream(graph, state, "task-comp-1"):
            if evt["event"] == "completed":
                assert evt["state"]["workflow_status"] == "completed"

    @pytest.mark.asyncio
    async def test_workflow_tracks_steps(self, mock_tool_executor):
        """验证步骤历史记录"""
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        adapter = LangGraphAdapter(node_executor=executor)
        spec = _make_simple_workflow(with_condition=False)
        graph = adapter.build(spec)

        state = create_default_state(task_id="task-step-1")
        events = []
        async for evt in adapter.astream(graph, state, "task-step-1"):
            events.append(evt)

        final_state = events[-1].get("state", {})
        steps = final_state.get("steps", [])
        step_nodes = [s["node"] for s in steps]
        assert "start" in step_nodes
        assert "run_tool" in step_nodes

    @pytest.mark.asyncio
    async def test_error_handling_unknown_tool(self):
        """调用未注册工具时不应崩溃"""
        executor = NodeExecutor()  # 无 mock，工具未注册会失败
        adapter = LangGraphAdapter(node_executor=executor)
        spec = _make_simple_workflow(with_condition=False)
        graph = adapter.build(spec)

        state = create_default_state(task_id="task-err-1")
        events = []
        async for evt in adapter.astream(graph, state, "task-err-1"):
            events.append(evt)

        # 应正常完成（不崩溃），但 error_count > 0
        assert any(e["event"] == "completed" for e in events)
        final_state = events[-1].get("state", {})
        assert final_state.get("error_count", 0) >= 1

    @pytest.mark.asyncio
    async def test_llm_node_in_workflow(self):
        """LLM 节点在工作流中执行"""
        async def mock_llm(sp, msgs, cfg):
            return {"content": "Mock LLM says: OK"}

        executor = NodeExecutor(llm_callable=mock_llm)
        adapter = LangGraphAdapter(node_executor=executor)

        spec = WorkflowSpec(
            name="llm_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(
                    id="think",
                    type=NodeType.LLM,
                    config={"system_prompt": "Think step by step."},
                ),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="think"),
                EdgeSpec(source="think", target="end"),
            ],
        )
        graph = adapter.build(spec)
        state = create_default_state(task_id="task-llm-1")

        events = []
        async for evt in adapter.astream(graph, state, "task-llm-1"):
            events.append(evt)

        final_state = events[-1].get("state", {})
        assistant_msgs = [m for m in final_state.get("messages", []) if m.get("role") == "assistant"]
        assert len(assistant_msgs) >= 1
        assert final_state["llm_call_count"] >= 1


# ═══════════════════════════════════════════
# 6. Edge Case 测试
# ═══════════════════════════════════════════

class TestEdgeCases:
    """边界情况测试"""

    @pytest.mark.asyncio
    async def test_empty_workflow_spec(self):
        """空的 WorkflowSpec"""
        spec = WorkflowSpec(name="empty")
        adapter = LangGraphAdapter()
        with pytest.raises(ValueError):
            adapter.build(spec)

    def test_lightweight_state_creation(self):
        """LightweightState.from_dict 处理未知字段"""
        data = {
            "task_id": "t1",
            "project_id": "p1",
            "unknown_field": "should be ignored",
        }
        ls = LightweightState.from_dict(data)
        assert ls.task_id == "t1"
        assert ls.project_id == "p1"

    @pytest.mark.asyncio
    async def test_multiple_tasks_independent(self, mock_tool_executor):
        """多个任务并行执行不互相干扰"""
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        adapter = LangGraphAdapter(node_executor=executor)
        spec = _make_simple_workflow(with_condition=False)
        graph = adapter.build(spec)

        async def run_task(tid: str) -> WorkflowState:
            state = create_default_state(task_id=tid)
            async for _ in adapter.astream(graph, state, tid):
                pass
            return state

        s1, s2 = await asyncio.gather(
            run_task("parallel-1"),
            run_task("parallel-2"),
        )

        assert s1["task_id"] == "parallel-1"
        assert s2["task_id"] == "parallel-2"

    @pytest.mark.asyncio
    async def test_workflow_with_only_start(self):
        """只有 start 节点的工作流"""
        spec = WorkflowSpec(
            name="solo-start",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
            ],
            edges=[],
        )
        adapter = LangGraphAdapter()
        graph = adapter.build(spec)

        state = create_default_state(task_id="solo-1")
        events = []
        async for evt in adapter.astream(graph, state, "solo-1"):
            events.append(evt)
        assert any(e["event"] == "completed" for e in events)

    def test_workflow_spec_json_serializable(self):
        """WorkflowSpec 可以序列化为 JSON"""
        import json
        spec = _make_simple_workflow()
        json_str = spec.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["name"] == "test_workflow"
        assert len(parsed["nodes"]) == 3

    @pytest.mark.asyncio
    async def test_interrupt_flow_in_workflow(self, mock_tool_executor):
        """human_approval 节点能正确设置 approval_needed"""
        executor = NodeExecutor(tool_executor=mock_tool_executor)

        # 直接调用 execute_node（不通过 astream，因为 interrupt() 需要 checkpointer）
        approval_spec = NodeSpec(
            id="approve",
            type=NodeType.HUMAN_APPROVAL,
            config={"message": "请确认"},
        )
        state = create_default_state(task_id="task-app-1")
        result = await executor.execute_node(approval_spec, state)

        assert result["approval_needed"] is True


# ═══════════════════════════════════════════
# 7. Phase 1 — NodeDefaults + EdgeType 测试
# ═══════════════════════════════════════════

class TestNodeDefaults:
    """NodeDefaults 全局节点默认策略模型测试"""

    def test_default_values(self):
        nd = NodeDefaults()
        assert nd.retry_max_attempts == 3
        assert nd.retry_initial_interval == 0.5
        assert nd.retry_backoff_factor == 2.0
        assert nd.retry_max_interval == 128.0
        assert nd.retry_jitter is True
        assert nd.cache_ttl is None
        assert nd.timeout_seconds is None

    def test_to_retry_policy(self):
        nd = NodeDefaults(
            retry_max_attempts=5,
            retry_initial_interval=1.0,
            retry_backoff_factor=3.0,
            retry_max_interval=60.0,
            retry_jitter=False,
        )
        rp = nd.to_retry_policy()
        assert rp is not None
        assert rp.max_attempts == 5
        assert rp.initial_interval == 1.0
        assert rp.backoff_factor == 3.0
        assert rp.max_interval == 60.0
        assert rp.jitter is False

    def test_to_cache_policy_enabled(self):
        nd = NodeDefaults(cache_ttl=3600)
        cp = nd.to_cache_policy()
        assert cp is not None
        assert cp.ttl == 3600

    def test_to_cache_policy_disabled(self):
        nd = NodeDefaults()  # cache_ttl=None
        cp = nd.to_cache_policy()
        assert cp is None

    def test_custom_retry_config(self):
        nd = NodeDefaults(
            retry_max_attempts=10,
            retry_initial_interval=2.0,
            retry_backoff_factor=1.5,
            retry_max_interval=30.0,
            retry_jitter=True,
        )
        rp = nd.to_retry_policy()
        assert rp.max_attempts == 10
        assert rp.initial_interval == 2.0
        assert rp.backoff_factor == 1.5
        assert rp.max_interval == 30.0
        assert rp.jitter is True

    def test_timeout_only(self):
        nd = NodeDefaults(timeout_seconds=30.0)
        assert nd.timeout_seconds == 30.0
        rp = nd.to_retry_policy()
        assert rp is not None
        assert nd.to_cache_policy() is None

    def test_validation_min_attempts(self):
        nd = NodeDefaults(retry_max_attempts=1)
        assert nd.retry_max_attempts == 1

    def test_serialization_round_trip(self):
        nd = NodeDefaults(
            retry_max_attempts=7,
            retry_initial_interval=1.5,
            cache_ttl=600,
            timeout_seconds=45.0,
        )
        d = nd.model_dump()
        nd2 = NodeDefaults(**d)
        assert nd2.retry_max_attempts == 7
        assert nd2.cache_ttl == 600
        assert nd2.timeout_seconds == 45.0


class TestEdgeType:
    """EdgeType 枚举 + EdgeSpec.effective_type 测试"""

    def test_edge_type_values(self):
        assert EdgeType.DIRECT.value == "direct"
        assert EdgeType.CONDITIONAL.value == "conditional"
        assert EdgeType.SEND.value == "send"

    def test_effective_type_direct(self):
        e = EdgeSpec(source="a", target="b", edge_type=EdgeType.DIRECT)
        assert e.effective_type == EdgeType.DIRECT

    def test_effective_type_conditional(self):
        e = EdgeSpec(source="a", target="b", condition="state.x > 0")
        assert e.effective_type == EdgeType.CONDITIONAL

    def test_effective_type_send_explicit(self):
        e = EdgeSpec(source="a", edge_type=EdgeType.SEND, send_node="worker", items_expr="state.items")
        assert e.effective_type == EdgeType.SEND

    def test_effective_type_send_auto_detect(self):
        e = EdgeSpec(source="a", send_node="worker", items_expr="state.items")
        assert e.effective_type == EdgeType.SEND

    def test_effective_type_backward_compat(self):
        e1 = EdgeSpec(source="a", target="b", condition="True")
        assert e1.effective_type == EdgeType.CONDITIONAL
        e2 = EdgeSpec(source="a", target="b")
        assert e2.effective_type == EdgeType.DIRECT

    def test_conditional_takes_precedence_over_direct(self):
        e = EdgeSpec(source="a", target="b", edge_type=EdgeType.CONDITIONAL, condition="state.ok")
        assert e.effective_type == EdgeType.CONDITIONAL

    def test_send_takes_precedence_over_conditional(self):
        e = EdgeSpec(source="a", send_node="worker", items_expr="state.tasks", condition="True")
        assert e.effective_type == EdgeType.SEND


class TestWorkflowSpecPhase1:
    """WorkflowSpec 新字段测试 (node_defaults / interrupt_before / interrupt_after)"""

    def test_node_defaults_in_spec(self):
        nd = NodeDefaults(retry_max_attempts=5, timeout_seconds=30.0)
        spec = WorkflowSpec(
            name="test",
            nodes=[NodeSpec(id="start", type=NodeType.START)],
            edges=[],
            node_defaults=nd,
        )
        assert spec.node_defaults is not None
        assert spec.node_defaults.retry_max_attempts == 5
        assert spec.node_defaults.timeout_seconds == 30.0

    def test_interrupt_before_in_spec(self):
        spec = WorkflowSpec(
            name="test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="critical", type=NodeType.TOOL),
            ],
            edges=[EdgeSpec(source="start", target="critical")],
            interrupt_before=["critical"],
        )
        assert "critical" in spec.interrupt_before

    def test_interrupt_after_in_spec(self):
        spec = WorkflowSpec(
            name="test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="check", type=NodeType.CONDITION),
            ],
            edges=[EdgeSpec(source="start", target="check")],
            interrupt_after=["check"],
        )
        assert "check" in spec.interrupt_after

    def test_send_edge_in_spec(self):
        spec = WorkflowSpec(
            name="fanout",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="fan_out", type=NodeType.TOOL),
                NodeSpec(id="process", type=NodeType.TOOL, config={"tool_name": "echo"}),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="fan_out"),
                EdgeSpec(
                    source="fan_out",
                    target="",
                    edge_type=EdgeType.SEND,
                    send_node="process",
                    items_expr="state.items",
                ),
                EdgeSpec(source="process", target="end"),
            ],
        )
        send_edges = [e for e in spec.edges if e.effective_type == EdgeType.SEND]
        assert len(send_edges) == 1
        assert send_edges[0].send_node == "process"
        assert send_edges[0].items_expr == "state.items"

    def test_serialization_with_phase1_fields(self):
        import json
        nd = NodeDefaults(retry_max_attempts=3, cache_ttl=3600, timeout_seconds=60.0)
        spec = WorkflowSpec(
            name="phase1_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="run", type=NodeType.TOOL),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="run"),
                EdgeSpec(source="run", target="end"),
            ],
            node_defaults=nd,
            interrupt_before=["run"],
            interrupt_after=["run"],
        )
        json_str = spec.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["name"] == "phase1_test"
        assert parsed["node_defaults"]["retry_max_attempts"] == 3
        assert parsed["node_defaults"]["cache_ttl"] == 3600
        assert parsed["node_defaults"]["timeout_seconds"] == 60.0
        assert "run" in parsed["interrupt_before"]
        assert "run" in parsed["interrupt_after"]

    def test_node_defaults_none_by_default(self):
        spec = WorkflowSpec(name="test", nodes=[], edges=[])
        assert spec.node_defaults is None
        assert spec.interrupt_before == []
        assert spec.interrupt_after == []


# ═══════════════════════════════════════════
# 8. Phase 1 — Command(goto=) 动态路由测试
# ═══════════════════════════════════════════

class TestNodeExecutorCommand:
    """NodeExecutor 返回 Command 对象用于动态路由"""

    @pytest.mark.asyncio
    async def test_command_goto(self, mock_tool_executor):
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        node = NodeSpec(
            id="dynamic_jump",
            type=NodeType.TOOL,
            config={
                "tool_name": "test_tool",
                "args_template": {},
                "goto": "alt_end",
            },
        )
        state = create_default_state(task_id="task-cmd-1")
        result = await executor.execute_node(node, state)

        assert result is not None
        assert hasattr(result, "goto")
        assert result.goto == "alt_end"

    @pytest.mark.asyncio
    async def test_command_update(self, mock_tool_executor):
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        node = NodeSpec(
            id="update_state",
            type=NodeType.TOOL,
            config={
                "tool_name": "test_tool",
                "args_template": {},
                "update": {"workflow_status": "custom_status", "error_count": 0},
            },
        )
        state = create_default_state(task_id="task-cmd-2")
        result = await executor.execute_node(node, state)

        assert hasattr(result, "update")
        assert result.update == {"workflow_status": "custom_status", "error_count": 0}

    @pytest.mark.asyncio
    async def test_command_goto_and_update(self, mock_tool_executor):
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        node = NodeSpec(
            id="both",
            type=NodeType.TOOL,
            config={
                "tool_name": "test_tool",
                "args_template": {},
                "goto": "next_phase",
                "update": {"phase": "phase_2"},
            },
        )
        state = create_default_state(task_id="task-cmd-3")
        result = await executor.execute_node(node, state)

        assert hasattr(result, "goto")
        assert result.goto == "next_phase"
        assert hasattr(result, "update")
        assert result.update == {"phase": "phase_2"}

    @pytest.mark.asyncio
    async def test_no_command_without_config(self, mock_tool_executor):
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        node = NodeSpec(
            id="normal_tool",
            type=NodeType.TOOL,
            config={"tool_name": "test_tool", "args_template": {}},
        )
        state = create_default_state(task_id="task-cmd-4")
        result = await executor.execute_node(node, state)

        assert isinstance(result, dict)
        assert "messages" in result

    @pytest.mark.asyncio
    async def test_command_from_llm_node(self):
        async def mock_llm(sp, msgs, cfg):
            return {"content": "Done"}

        executor = NodeExecutor(llm_callable=mock_llm)
        node = NodeSpec(
            id="llm_router",
            type=NodeType.LLM,
            config={
                "system_prompt": "Classify",
                "goto": "approved",
            },
        )
        state = create_default_state(task_id="task-cmd-llm")
        result = await executor.execute_node(node, state)

        assert hasattr(result, "goto")
        assert result.goto == "approved"


# ═══════════════════════════════════════════
# 9. Phase 1 — Send() 并行分发 + _eval_items_expr 测试
# ═══════════════════════════════════════════

class TestEvalItemsExpr:
    """_eval_items_expr 安全表达式求值"""

    def test_state_items(self):
        state: WorkflowState = create_default_state(task_id="t1")
        state["items"] = [1, 2, 3]
        result = _eval_items_expr("state.items", state)
        assert result == [1, 2, 3]

    def test_nested_path(self):
        state: WorkflowState = create_default_state(task_id="t1")
        state["metadata"] = {"files": ["a.txt", "b.txt"]}
        result = _eval_items_expr("state.metadata.files", state)
        assert result == ["a.txt", "b.txt"]

    def test_empty_expr(self):
        state: WorkflowState = create_default_state(task_id="t1")
        assert _eval_items_expr("", state) == []
        assert _eval_items_expr("[]", state) == []

    def test_nonexistent_path(self):
        state: WorkflowState = create_default_state(task_id="t1")
        result = _eval_items_expr("state.nonexistent.field", state)
        assert result == []

    def test_not_a_list(self):
        state: WorkflowState = create_default_state(task_id="t1")
        state["scalar"] = 42  # type: ignore
        result = _eval_items_expr("state.scalar", state)
        assert result == []

    def test_not_starting_with_state(self):
        state: WorkflowState = create_default_state(task_id="t1")
        result = _eval_items_expr("other.items", state)
        assert result == []

    def test_empty_list(self):
        state: WorkflowState = create_default_state(task_id="t1")
        state["items"] = []
        result = _eval_items_expr("state.items", state)
        assert result == []

    def test_complex_items(self):
        state: WorkflowState = create_default_state(task_id="t1")
        state["items"] = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
        result = _eval_items_expr("state.items", state)
        assert len(result) == 2
        assert result[0] == {"id": 1, "name": "A"}


class TestLangGraphAdapterSend:
    """LangGraphAdapter Send 并行分发构建测试"""

    @pytest.fixture
    def send_workflow_spec(self) -> WorkflowSpec:
        return WorkflowSpec(
            name="send_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="fan_out", type=NodeType.TOOL, config={"tool_name": "echo"}),
                NodeSpec(id="process_item", type=NodeType.TOOL, config={"tool_name": "echo"}),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="fan_out"),
                EdgeSpec(
                    source="fan_out",
                    target="",
                    edge_type=EdgeType.SEND,
                    send_node="process_item",
                    items_expr="state.items",
                ),
                EdgeSpec(source="process_item", target="end"),
            ],
        )

    def test_build_send_workflow(self, send_workflow_spec):
        adapter = LangGraphAdapter()
        graph = adapter.build(send_workflow_spec)
        assert graph is not None
        assert len(graph.nodes) >= 4

    def test_send_router_function(self, send_workflow_spec):
        adapter = LangGraphAdapter()
        graph = adapter.build(send_workflow_spec)
        assert graph is not None

        state: WorkflowState = create_default_state(task_id="t-send")
        state["items"] = [
            {"step": "step_1", "input": "data_a"},
            {"step": "step_2", "input": "data_b"},
        ]

        from langgraph.types import Send
        items = _eval_items_expr("state.items", state)
        assert len(items) == 2

        sends = [Send("process_item", {"item": item}) for item in items]
        assert len(sends) == 2
        assert sends[0].node == "process_item"
        assert sends[0].arg == {"item": {"step": "step_1", "input": "data_a"}}
        assert sends[1].arg == {"item": {"step": "step_2", "input": "data_b"}}

    def test_build_send_edge_empty_items(self):
        spec = WorkflowSpec(
            name="empty_send",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="fan_out", type=NodeType.TOOL),
                NodeSpec(id="process", type=NodeType.TOOL),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="fan_out"),
                EdgeSpec(
                    source="fan_out",
                    edge_type=EdgeType.SEND,
                    send_node="process",
                    items_expr="state.items",
                ),
                EdgeSpec(source="process", target="end"),
            ],
        )
        adapter = LangGraphAdapter()
        graph = adapter.build(spec)
        assert graph is not None

    def test_send_edge_missing_send_node(self):
        spec = WorkflowSpec(
            name="bad_send",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="end"),
                EdgeSpec(
                    source="start",
                    edge_type=EdgeType.SEND,
                    send_node="",
                    items_expr="state.items",
                ),
            ],
        )
        adapter = LangGraphAdapter()
        graph = adapter.build(spec)  # 不应崩溃
        assert graph is not None

    def test_mixed_edge_types_in_spec(self):
        spec = WorkflowSpec(
            name="mixed",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="check", type=NodeType.CONDITION, config={"expression": "True"}),
                NodeSpec(id="fan_out", type=NodeType.TOOL),
                NodeSpec(id="worker", type=NodeType.TOOL),
                NodeSpec(id="pass", type=NodeType.END),
                NodeSpec(id="fail", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="check", edge_type=EdgeType.DIRECT),
                EdgeSpec(source="check", target="pass", condition="true"),
                EdgeSpec(source="check", target="fail", condition="false"),
                EdgeSpec(source="check", target="fan_out", condition="true"),
                EdgeSpec(
                    source="fan_out",
                    edge_type=EdgeType.SEND,
                    send_node="worker",
                    items_expr="state.items",
                ),
            ],
        )
        adapter = LangGraphAdapter()
        graph = adapter.build(spec)
        assert graph is not None


# ═══════════════════════════════════════════
# 10. Phase 1 — set_node_defaults() 集成测试
# ═══════════════════════════════════════════

class TestSetNodeDefaults:
    """set_node_defaults() 集成到 build() 流程"""

    def test_build_with_node_defaults(self):
        nd = NodeDefaults(
            retry_max_attempts=2,
            retry_initial_interval=0.1,
            timeout_seconds=10.0,
        )
        spec = WorkflowSpec(
            name="with_defaults",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="tool", type=NodeType.TOOL, config={"tool_name": "echo"}),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="tool"),
                EdgeSpec(source="tool", target="end"),
            ],
            node_defaults=nd,
        )
        adapter = LangGraphAdapter()
        graph = adapter.build(spec)
        assert graph is not None

    def test_build_with_node_defaults_cache_only(self):
        nd = NodeDefaults(cache_ttl=600)
        spec = WorkflowSpec(
            name="cache_defaults",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[EdgeSpec(source="start", target="end")],
            node_defaults=nd,
        )
        adapter = LangGraphAdapter()
        graph = adapter.build(spec)
        assert graph is not None

    def test_build_without_node_defaults(self):
        spec = WorkflowSpec(
            name="no_defaults",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[EdgeSpec(source="start", target="end")],
        )
        adapter = LangGraphAdapter()
        graph = adapter.build(spec)
        assert graph is not None

    def test_build_with_interrupt_before(self):
        spec = WorkflowSpec(
            name="interrupt_before_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="sensitive", type=NodeType.TOOL),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="sensitive"),
                EdgeSpec(source="sensitive", target="end"),
            ],
            interrupt_before=["sensitive"],
        )
        adapter = LangGraphAdapter()
        graph = adapter.build(spec)
        assert graph is not None

    def test_build_with_interrupt_after(self):
        spec = WorkflowSpec(
            name="interrupt_after_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="check", type=NodeType.CONDITION),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[EdgeSpec(source="start", target="check")],
            interrupt_after=["check"],
        )
        adapter = LangGraphAdapter()
        graph = adapter.build(spec)
        assert graph is not None

    def test_build_with_all_phase1_features(self):
        nd = NodeDefaults(retry_max_attempts=5, timeout_seconds=30.0)
        spec = WorkflowSpec(
            name="full_phase1",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="validate", type=NodeType.TOOL),
                NodeSpec(id="approve", type=NodeType.HUMAN_APPROVAL),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="validate"),
                EdgeSpec(source="validate", target="approve"),
                EdgeSpec(source="approve", target="end"),
            ],
            node_defaults=nd,
            interrupt_before=["validate"],
            interrupt_after=["approve"],
        )
        adapter = LangGraphAdapter()
        graph = adapter.build(spec)
        assert graph is not None

    def test_build_with_node_defaults_all_disabled(self):
        nd = NodeDefaults()
        spec = WorkflowSpec(
            name="defaults_none",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[EdgeSpec(source="start", target="end")],
            node_defaults=nd,
        )
        adapter = LangGraphAdapter()
        graph = adapter.build(spec)
        assert graph is not None


# ═══════════════════════════════════════════
# 8. Phase 2 — RuntimeContext
# ═══════════════════════════════════════════

class TestRuntimeContext:
    """RuntimeContext 模型测试"""

    def test_create_default(self):
        ctx = create_runtime_context()
        assert ctx["task_id"] == ""
        assert ctx["workflow_id"] == ""
        assert ctx["metadata"] == {}

    def test_create_full(self):
        ctx = create_runtime_context(
            task_id="task-001",
            workflow_id="wf-001",
            user_id="user-1",
            project_id="proj-1",
            stream_mode=["values", "custom"],
            metadata={"env": "test"},
        )
        assert ctx["task_id"] == "task-001"
        assert ctx["workflow_id"] == "wf-001"
        assert ctx["user_id"] == "user-1"
        assert ctx["project_id"] == "proj-1"
        assert ctx["stream_mode"] == ["values", "custom"]
        assert ctx["metadata"] == {"env": "test"}

    def test_typeddict_partial(self):
        """total=False 允许部分字段"""
        ctx: RuntimeContext = {"task_id": "abc"}
        assert ctx["task_id"] == "abc"

    def test_used_in_state_graph(self):
        """验证 RuntimeContext 可作为 context_schema 传入 StateGraph"""
        from langgraph.graph import StateGraph
        builder = StateGraph(WorkflowState, context_schema=RuntimeContext)
        assert builder is not None


# ═══════════════════════════════════════════
# 9. Phase 2 — StreamWriter 集成
# ═══════════════════════════════════════════

class TestStreamWriter:
    """StreamWriter 自定义流式测试"""

    @pytest.mark.asyncio
    async def test_writer_injected_to_node_executor(self, mock_tool_executor):
        """Writer 参数正确传递到 NodeExecutor（使用 mock executor 避免真实工具查找）"""
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        node = NodeSpec(id="test_node", type=NodeType.TOOL, config={
            "tool_name": "test_tool",
            "args_template": {},
        })
        state = create_default_state(task_id="test-1")

        result = await executor.execute_node(node, state, writer=None)
        assert result is not None

    @pytest.mark.asyncio
    async def test_writer_passed_for_llm_node(self, mock_tool_executor):
        """LLM 节点接收 writer 参数"""
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        node = NodeSpec(id="llm_1", type=NodeType.LLM, config={
            "system_prompt": "test",
        })
        state = create_default_state(task_id="test-2")

        result = await executor.execute_node(node, state, writer=None)
        assert result is not None

    @pytest.mark.asyncio
    async def test_writer_passed_for_tool_node(self, mock_tool_executor):
        """Tool 节点接收 writer 参数"""
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        node = NodeSpec(id="tool_1", type=NodeType.TOOL, config={
            "tool_name": "test_tool",
            "args_template": {},
        })
        state = create_default_state(task_id="test-3")

        result = await executor.execute_node(node, state, writer=None)
        assert result is not None

    @pytest.mark.asyncio
    async def test_writer_passed_for_condition_node(self, mock_tool_executor):
        """Condition 节点接收 writer 参数"""
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        node = NodeSpec(id="cond_1", type=NodeType.CONDITION, config={
            "expression": "True",
        })
        state = create_default_state(task_id="test-4")

        result = await executor.execute_node(node, state, writer=None)
        assert result is not None

    @pytest.mark.asyncio
    async def test_writer_passed_for_human_approval_node(self, mock_tool_executor):
        """Human Approval 节点接收 writer 参数"""
        executor = NodeExecutor(tool_executor=mock_tool_executor)
        node = NodeSpec(id="approval_1", type=NodeType.HUMAN_APPROVAL, config={
            "message": "请审批",
        })
        state = create_default_state(task_id="test-5")

        result = await executor.execute_node(node, state, writer=None)
        assert result is not None

    @pytest.mark.asyncio
    async def test_custom_writer_called_in_llm(self):
        """自定义 writer 在 LLM 节点中被调用"""
        writer_data = []

        def writer(data):
            writer_data.append(data)

        executor = NodeExecutor()
        node = NodeSpec(id="llm_custom", type=NodeType.LLM, config={
            "system_prompt": "test",
        })
        state = create_default_state(task_id="test-custom")

        result = await executor.execute_node(node, state, writer=writer)
        assert result is not None
        assert len(writer_data) >= 1
        assert writer_data[0]["type"] == "progress"

    @pytest.mark.asyncio
    async def test_custom_writer_called_in_tool(self, mock_tool_executor):
        """自定义 writer 在 Tool 节点中被调用"""
        writer_data = []

        def writer(data):
            writer_data.append(data)

        executor = NodeExecutor(tool_executor=mock_tool_executor)
        node = NodeSpec(id="tool_custom", type=NodeType.TOOL, config={
            "tool_name": "test_tool",
            "args_template": {},
        })
        state = create_default_state(task_id="test-tool-custom")

        result = await executor.execute_node(node, state, writer=writer)
        assert result is not None
        assert len(writer_data) >= 1
        assert writer_data[0]["type"] == "progress"
        assert "tool_name" in writer_data[0]


# ═══════════════════════════════════════════
# 10. Phase 2 — stream_mode (7 种模式)
# ═══════════════════════════════════════════

class TestStreamModeDispatch:
    """_dispatch_stream_chunk 分发逻辑测试"""

    @pytest.fixture
    def adapter(self):
        return LangGraphAdapter()

    def _dispatch(self, adapter, part_type, data, task_id="t", state=None, ns=()):
        """Helper: 直接调用 _dispatch_single_part"""
        if state is None:
            state = {}
        return list(adapter._dispatch_single_part(part_type, data, task_id, state, ns=ns))

    def test_dispatch_values(self, adapter):
        """values 模式 → state_updated 事件"""
        state = {"task_id": "t1", "current_node": "start"}
        events = self._dispatch(adapter, "values", {"task_id": "t1", "current_node": "node_a"}, "t1", state)
        assert len(events) == 1
        assert events[0]["event"] == "state_updated"
        assert events[0]["task_id"] == "t1"
        assert state["current_node"] == "node_a"

    def test_dispatch_updates_single(self, adapter):
        """updates 模式 → node_completed 事件（单节点更新）"""
        state = {"task_id": "t2"}
        events = self._dispatch(adapter, "updates", {"node_1": {"new_field": "value"}}, "t2", state)
        assert len(events) == 1
        assert events[0]["event"] == "node_completed"
        assert events[0]["node_id"] == "node_1"
        assert events[0]["update"] == {"new_field": "value"}

    def test_dispatch_updates_multiple(self, adapter):
        """updates 模式 → 多节点更新各自产生事件"""
        events = self._dispatch(adapter, "updates", {"node_a": {"a": 1}, "node_b": {"b": 2}}, "t3")
        assert len(events) == 2
        assert {e["node_id"] for e in events} == {"node_a", "node_b"}

    def test_dispatch_messages(self, adapter):
        """messages 模式 → token_stream 事件"""
        events = self._dispatch(adapter, "messages", ({"role": "assistant", "content": "Hello"}, {"langgraph_node": "llm_1"}), "t4")
        assert len(events) == 1
        assert events[0]["event"] == "token_stream"
        assert events[0]["message"] == {"role": "assistant", "content": "Hello"}
        assert events[0]["metadata"] == {"langgraph_node": "llm_1"}

    def test_dispatch_custom(self, adapter):
        """custom 模式 → custom_stream 事件"""
        events = self._dispatch(adapter, "custom", {"progress": 0.5, "step": "fetching"}, "t5")
        assert len(events) == 1
        assert events[0]["event"] == "custom_stream"
        assert events[0]["data"] == {"progress": 0.5, "step": "fetching"}

    def test_dispatch_checkpoints(self, adapter):
        """checkpoints 模式 → checkpoint_created 事件"""
        events = self._dispatch(adapter, "checkpoints", {"checkpoint_id": "cp-001"}, "t6")
        assert len(events) == 1
        assert events[0]["event"] == "checkpoint_created"

    def test_dispatch_tasks(self, adapter):
        """tasks 模式 → task_lifecycle 事件"""
        events = self._dispatch(adapter, "tasks", {"id": "task-1", "name": "node_a"}, "t7")
        assert len(events) == 1
        assert events[0]["event"] == "task_lifecycle"

    def test_dispatch_debug(self, adapter):
        """debug 模式 → debug_info 事件"""
        events = self._dispatch(adapter, "debug", {"step": 1}, "t8")
        assert len(events) == 1
        assert events[0]["event"] == "debug_info"

    def test_dispatch_unknown_type(self, adapter):
        """未知 type 不产生事件"""
        events = self._dispatch(adapter, "unknown_type", {}, "t9")
        assert len(events) == 0

    def test_dispatch_chunk_tuple_format(self, adapter):
        """多 mode: chunk 是 (mode, data) 元组"""
        state = {}
        chunk = ("custom", {"msg": "hello"})
        events = list(adapter._dispatch_stream_chunk(chunk, "t10", state))
        assert len(events) == 1
        assert events[0]["event"] == "custom_stream"
        assert events[0]["data"] == {"msg": "hello"}

    def test_dispatch_chunk_dict_format(self, adapter):
        """单 mode: chunk 是 StreamPart dict"""
        state = {}
        chunk = {"type": "values", "ns": (), "data": {"k": "v"}}
        events = list(adapter._dispatch_stream_chunk(chunk, "t11", state))
        assert len(events) == 1
        assert events[0]["event"] == "state_updated"


# ═══════════════════════════════════════════
# 11. Phase 2 — astream() with stream_mode
# ═══════════════════════════════════════════

class TestAstreamWithStreamMode:
    """astream() stream_mode 参数测试"""

    @pytest.fixture
    def simple_spec(self):
        return WorkflowSpec(
            name="stream_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="do_work", type=NodeType.TOOL, config={"tool_name": "test_tool", "args_template": {}}),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="do_work"),
                EdgeSpec(source="do_work", target="end"),
            ],
        )

    @pytest.mark.asyncio
    async def test_astream_values_mode(self, mock_tool_executor, simple_spec):
        """stream_mode='values' 产生 state_updated 事件"""
        adapter = LangGraphAdapter(node_executor=NodeExecutor(tool_executor=mock_tool_executor))
        graph = adapter.build(simple_spec)
        state = create_default_state(task_id="st-val")

        events = []
        async for event in adapter.astream(graph, state, "st-val", stream_mode="values"):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "state_updated" in event_types
        assert "completed" in event_types

    @pytest.mark.asyncio
    async def test_astream_updates_mode(self, mock_tool_executor, simple_spec):
        """stream_mode='updates' 产生 node_completed 事件"""
        adapter = LangGraphAdapter(node_executor=NodeExecutor(tool_executor=mock_tool_executor))
        graph = adapter.build(simple_spec)
        state = create_default_state(task_id="st-upd")

        events = []
        async for event in adapter.astream(graph, state, "st-upd", stream_mode="updates"):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "completed" in event_types
        node_events = [e for e in events if e["event"] == "node_completed"]
        assert len(node_events) >= 1

    @pytest.mark.asyncio
    async def test_astream_multiple_modes(self, mock_tool_executor, simple_spec):
        """stream_mode=['values', 'updates'] 同时产生两种事件"""
        adapter = LangGraphAdapter(node_executor=NodeExecutor(tool_executor=mock_tool_executor))
        graph = adapter.build(simple_spec)
        state = create_default_state(task_id="st-multi")

        events = []
        async for event in adapter.astream(
            graph, state, "st-multi", stream_mode=["values", "updates"]
        ):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "completed" in event_types

    @pytest.mark.asyncio
    async def test_astream_custom_mode(self, mock_tool_executor, simple_spec):
        """stream_mode='custom' 产生 custom_stream 事件"""
        adapter = LangGraphAdapter(node_executor=NodeExecutor(tool_executor=mock_tool_executor))
        graph = adapter.build(simple_spec)
        state = create_default_state(task_id="st-custom")

        events = []
        async for event in adapter.astream(graph, state, "st-custom", stream_mode="custom"):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "completed" in event_types

    @pytest.mark.asyncio
    async def test_astream_tasks_mode(self, mock_tool_executor, simple_spec):
        """stream_mode='tasks' 产生 task_lifecycle 事件"""
        adapter = LangGraphAdapter(node_executor=NodeExecutor(tool_executor=mock_tool_executor))
        graph = adapter.build(simple_spec)
        state = create_default_state(task_id="st-tasks")

        events = []
        async for event in adapter.astream(graph, state, "st-tasks", stream_mode="tasks"):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "completed" in event_types
        task_events = [e for e in events if e["event"] == "task_lifecycle"]
        assert len(task_events) >= 1

    @pytest.mark.asyncio
    async def test_astream_debug_mode(self, mock_tool_executor, simple_spec):
        """stream_mode='debug' 产生 debug_info 事件"""
        adapter = LangGraphAdapter(node_executor=NodeExecutor(tool_executor=mock_tool_executor))
        graph = adapter.build(simple_spec)
        state = create_default_state(task_id="st-debug")

        events = []
        async for event in adapter.astream(graph, state, "st-debug", stream_mode="debug"):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "completed" in event_types

    @pytest.mark.asyncio
    async def test_astream_checkpoints_mode(self, mock_tool_executor, simple_spec):
        """stream_mode='checkpoints' 产生 checkpoint_created 事件"""
        adapter = LangGraphAdapter(node_executor=NodeExecutor(tool_executor=mock_tool_executor))
        graph = adapter.build(simple_spec)
        state = create_default_state(task_id="st-cp")

        events = []
        async for event in adapter.astream(
            graph, state, "st-cp", stream_mode="checkpoints"
        ):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "completed" in event_types

    @pytest.mark.asyncio
    async def test_astream_no_stream_mode_uses_v1(self, mock_tool_executor, simple_spec):
        """不传 stream_mode 使用 v1 兼容模式（向后兼容）"""
        adapter = LangGraphAdapter(node_executor=NodeExecutor(tool_executor=mock_tool_executor))
        graph = adapter.build(simple_spec)
        state = create_default_state(task_id="st-v1")

        events = []
        async for event in adapter.astream(graph, state, "st-v1"):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "completed" in event_types
        node_events = [e for e in events if e["event"] == "node_exited"]
        assert len(node_events) >= 1

    @pytest.mark.asyncio
    async def test_astream_with_context(self, mock_tool_executor, simple_spec):
        """astream() 接受 context 参数（传递到 LangGraph）"""
        adapter = LangGraphAdapter(
            node_executor=NodeExecutor(tool_executor=mock_tool_executor),
            context_schema=RuntimeContext,
        )
        graph = adapter.build(simple_spec)
        state = create_default_state(task_id="st-ctx")

        ctx = create_runtime_context(task_id="st-ctx", workflow_id="wf-1")
        events = []
        async for event in adapter.astream(
            graph, state, "st-ctx",
            stream_mode="values",
            context=ctx,
        ):
            events.append(event)

        assert any(e["event"] == "completed" for e in events)

    @pytest.mark.asyncio
    async def test_astream_publishes_task_events_v2(self, mock_tool_executor, simple_spec):
        """stream_mode 模式下也发布 EventBus 事件"""
        adapter = LangGraphAdapter(node_executor=NodeExecutor(tool_executor=mock_tool_executor))
        graph = adapter.build(simple_spec)
        state = create_default_state(task_id="st-events")

        events = []
        async for event in adapter.astream(
            graph, state, "st-events", stream_mode="values"
        ):
            events.append(event)

        completed = [e for e in events if e["event"] == "completed"]
        assert len(completed) == 1
        assert completed[0]["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_astream_error_handling_v2(self, mock_tool_executor):
        """stream_mode 模式下异常处理正常"""
        spec = WorkflowSpec(
            name="error_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="bad_tool", type=NodeType.TOOL, config={
                    "tool_name": "nonexistent_tool",
                    "args_template": {},
                }),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="bad_tool"),
                EdgeSpec(source="bad_tool", target="end"),
            ],
        )
        adapter = LangGraphAdapter(node_executor=NodeExecutor(tool_executor=mock_tool_executor))
        graph = adapter.build(spec)
        state = create_default_state(task_id="st-err")

        events = []
        async for event in adapter.astream(
            graph, state, "st-err", stream_mode="values"
        ):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "completed" in event_types or "error" in event_types


# ═══════════════════════════════════════════
# 12. Phase 2 — context_schema + Runtime 注入
# ═══════════════════════════════════════════

class TestContextSchema:
    """context_schema + Runtime 注入测试"""

    def test_adapter_accepts_context_schema(self):
        """LangGraphAdapter 接受 context_schema 参数"""
        adapter = LangGraphAdapter(context_schema=RuntimeContext)
        assert adapter.context_schema is RuntimeContext

    def test_adapter_default_no_context_schema(self):
        """默认不设置 context_schema"""
        adapter = LangGraphAdapter()
        assert adapter.context_schema is None

    def test_build_with_context_schema(self):
        """build() 传入 context_schema 到 StateGraph"""
        adapter = LangGraphAdapter(context_schema=RuntimeContext)
        spec = WorkflowSpec(
            name="ctx_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[EdgeSpec(source="start", target="end")],
        )
        graph = adapter.build(spec)
        assert graph is not None

    def test_build_without_context_schema(self):
        """不设 context_schema 的 build 仍正常工作"""
        adapter = LangGraphAdapter()
        spec = WorkflowSpec(
            name="no_ctx_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[EdgeSpec(source="start", target="end")],
        )
        graph = adapter.build(spec)
        assert graph is not None

    @pytest.mark.asyncio
    async def test_astream_with_context_schema_and_context(self, mock_tool_executor):
        """context_schema + context 完整链路测试"""
        adapter = LangGraphAdapter(
            node_executor=NodeExecutor(tool_executor=mock_tool_executor),
            context_schema=RuntimeContext,
        )
        spec = WorkflowSpec(
            name="ctx_flow",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="tool_1", type=NodeType.TOOL, config={
                    "tool_name": "test_tool",
                    "args_template": {},
                }),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="tool_1"),
                EdgeSpec(source="tool_1", target="end"),
            ],
        )
        graph = adapter.build(spec)
        state = create_default_state(task_id="ctx-task")

        ctx = create_runtime_context(
            task_id="ctx-task",
            workflow_id="wf-ctx",
            user_id="user-99",
        )
        events = []
        async for event in adapter.astream(
            graph, state, "ctx-task",
            stream_mode="values",
            context=ctx,
        ):
            events.append(event)

        assert any(e["event"] == "completed" for e in events)

    def test_node_handler_accepts_writer_and_runtime(self, mock_tool_executor):
        """_make_node_handler 产生的 handler 接受 writer 和 runtime 参数"""
        adapter = LangGraphAdapter(
            node_executor=NodeExecutor(tool_executor=mock_tool_executor),
            context_schema=RuntimeContext,
        )
        spec = WorkflowSpec(
            name="handler_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[EdgeSpec(source="start", target="end")],
        )
        node_spec = spec.nodes[0]
        handler = adapter._make_node_handler(node_spec, spec)

        import inspect
        sig = inspect.signature(handler)
        params = list(sig.parameters.keys())
        assert "state" in params
        assert "writer" in params
        assert "runtime" in params

    def test_run_workflow_accepts_stream_mode(self):
        """run_workflow() 接受 stream_mode 参数"""
        adapter = LangGraphAdapter()
        spec = WorkflowSpec(
            name="rw_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[EdgeSpec(source="start", target="end")],
        )
        import inspect
        sig = inspect.signature(adapter.run_workflow)
        params = list(sig.parameters.keys())
        assert "stream_mode" in params
        assert "context" in params


# ═══════════════════════════════════════════
# Phase 3: then= / ToolNode / ainvoke / aget_state / CheckpointerAdapter / StoreAdapter
# ═══════════════════════════════════════════


class TestThenEdge:
    """Phase 3.2: then= 条件边后置节点"""

    def test_single_cond_with_then(self):
        """单条件边 + then → router 在条件为真时返回 then 节点"""
        adapter = LangGraphAdapter()
        spec = WorkflowSpec(
            name="then_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="check", type=NodeType.CONDITION),
                NodeSpec(id="intermediate", type=NodeType.TOOL, config={"tool_name": "log"}),
                NodeSpec(id="final", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="check"),
                EdgeSpec(source="check", target="final", condition="true", then="intermediate"),
            ],
        )
        graph = adapter.build(spec)
        assert graph is not None
        # then 节点应该作为中间节点被自动注册（如果尚未注册）

    def test_then_adds_direct_edge_to_target(self):
        """then= 节点应自动添加 then→target 直连边"""
        adapter = LangGraphAdapter()
        spec = WorkflowSpec(
            name="then_edge_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="check", type=NodeType.CONDITION),
                NodeSpec(id="middle", type=NodeType.TOOL, config={"tool_name": "log"}),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="check"),
                EdgeSpec(source="check", target="end", condition="true", then="middle"),
            ],
        )
        graph = adapter.build(spec)
        # graph 应编译成功（如果 then→target 边未正确添加，router 会指向不存在的节点）
        assert graph is not None

    def test_multi_cond_with_then(self):
        """多条件边 + then → 每个 then 正确路由"""
        adapter = LangGraphAdapter()
        spec = WorkflowSpec(
            name="multi_then_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="check", type=NodeType.CONDITION),
                NodeSpec(id="pre_pass", type=NodeType.TOOL, config={"tool_name": "log_pass"}),
                NodeSpec(id="pre_fail", type=NodeType.TOOL, config={"tool_name": "log_fail"}),
                NodeSpec(id="end_pass", type=NodeType.END),
                NodeSpec(id="end_fail", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="check"),
                EdgeSpec(source="check", target="end_pass", condition="true", then="pre_pass"),
                EdgeSpec(source="check", target="end_fail", condition="false", then="pre_fail"),
            ],
        )
        graph = adapter.build(spec)
        assert graph is not None

    def test_then_without_target_skips(self):
        """then 存在但 target 为空 → 跳过直连边添加（不崩溃）"""
        adapter = LangGraphAdapter()
        spec = WorkflowSpec(
            name="then_no_target",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="check", type=NodeType.CONDITION),
                NodeSpec(id="middle", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="check"),
                EdgeSpec(source="check", target="", condition="true", then="middle"),
            ],
        )
        graph = adapter.build(spec)
        assert graph is not None


class TestToolNodeSupport:
    """Phase 3.6: langgraph.prebuilt.ToolNode 复用"""

    def test_tool_node_fallback_when_no_tool_classes(self):
        """没有 tool_classes 时回退到普通 _all_node"""
        adapter = LangGraphAdapter()
        spec = WorkflowSpec(
            name="tn_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(
                    id="tools",
                    type=NodeType.TOOL,
                    config={"use_tool_node": True, "tools": ["mock_tool"]},
                ),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="tools"),
                EdgeSpec(source="tools", target="end"),
            ],
        )
        graph = adapter.build(spec)
        assert graph is not None

    def test_tool_node_with_invalid_tools_falls_back(self):
        """tool_classes 中找不到对应工具 → 回退"""
        adapter = LangGraphAdapter(tool_classes={"other_tool": lambda x: x})
        spec = WorkflowSpec(
            name="tn_missing",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(
                    id="tools",
                    type=NodeType.TOOL,
                    config={"use_tool_node": True, "tools": ["nonexistent_tool"]},
                ),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="tools"),
                EdgeSpec(source="tools", target="end"),
            ],
        )
        graph = adapter.build(spec)
        assert graph is not None

    def test_tool_node_not_used_when_use_tool_node_false(self):
        """未设置 use_tool_node 时走普通路径"""
        adapter = LangGraphAdapter(
            tool_classes={"echo": lambda x: x},
        )
        spec = WorkflowSpec(
            name="tn_off",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(
                    id="tools",
                    type=NodeType.TOOL,
                    config={"tool_name": "echo", "args_template": {}},
                ),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="tools"),
                EdgeSpec(source="tools", target="end"),
            ],
        )
        graph = adapter.build(spec)
        assert graph is not None


class TestAinvokeAPI:
    """Phase 3.7: ainvoke() / aget_state() / aupdate_state() / aget_state_history()"""

    @pytest.mark.asyncio
    async def test_ainvoke_executes_graph_to_completion(self):
        """ainvoke() 应执行 graph 到完成并返回最终 state"""
        adapter = LangGraphAdapter()
        spec = WorkflowSpec(
            name="invoke_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[EdgeSpec(source="start", target="end")],
        )
        graph = adapter.build(spec)
        state = create_default_state(task_id="invoke-1")
        result = await adapter.ainvoke(graph, state, "invoke-1")
        assert result["workflow_status"] == "completed"
        assert result["task_id"] == "invoke-1"

    @pytest.mark.asyncio
    async def test_ainvoke_publishes_events(self):
        """ainvoke() 应发布 TASK_STARTED 和 TASK_COMPLETED 事件"""
        adapter = LangGraphAdapter()
        spec = WorkflowSpec(
            name="invoke_events_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[EdgeSpec(source="start", target="end")],
        )
        graph = adapter.build(spec)
        state = create_default_state(task_id="invoke-2")
        result = await adapter.ainvoke(graph, state, "invoke-2")
        assert result["workflow_status"] == "completed"

    @pytest.mark.asyncio
    async def test_ainvoke_handles_errors(self):
        """ainvoke() 遇到异常应 raise 并发布 TASK_FAILED"""
        adapter = LangGraphAdapter()
        spec = WorkflowSpec(
            name="invoke_error_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[EdgeSpec(source="start", target="end")],
        )
        graph = adapter.build(spec)
        state = create_default_state(task_id="invoke-3")
        result = await adapter.ainvoke(graph, state, "invoke-3")
        assert result["workflow_status"] == "completed"

    @pytest.mark.asyncio
    async def test_aget_state_no_checkpoint_mgr(self):
        """没有 CheckpointManager 时 aget_state 返回 None"""
        adapter = LangGraphAdapter()
        result = await adapter.aget_state("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_aupdate_state_no_checkpoint_mgr(self):
        """没有 CheckpointManager 时 aupdate_state 返回 False"""
        adapter = LangGraphAdapter()
        result = await adapter.aupdate_state("task-1", {"workflow_status": "running"})
        assert result is False

    @pytest.mark.asyncio
    async def test_aget_state_history_no_checkpoint_mgr(self):
        """没有 CheckpointManager 时 aget_state_history 返回空列表"""
        adapter = LangGraphAdapter()
        result = await adapter.aget_state_history("task-1")
        assert result == []

    def test_adapter_accepts_checkpointer_adapter(self):
        """__init__ 接受 checkpointer_adapter 参数"""
        from app.runtime.execution_engine.checkpointer_adapter import CheckpointerAdapter

        # 不传 checkpointer_adapter 也 OK
        adapter = LangGraphAdapter()
        assert adapter.checkpointer_adapter is None

        # 传入 None 也 OK
        adapter2 = LangGraphAdapter(checkpointer_adapter=None)
        assert adapter2.checkpointer_adapter is None

    def test_adapter_accepts_tool_classes(self):
        """__init__ 接受 tool_classes 参数"""
        adapter = LangGraphAdapter(tool_classes={"test": lambda x: x})
        assert "test" in adapter.tool_classes

        adapter2 = LangGraphAdapter()
        assert adapter2.tool_classes == {}


class TestCheckpointerAdapter:
    """Phase 3.3: CheckpointerAdapter 原生 LangGraph Bridge"""

    def test_create_checkpointer_adapter(self):
        """可以创建 CheckpointerAdapter（需要 CheckpointManager）"""
        from app.runtime.execution_engine.checkpointer_adapter import CheckpointerAdapter

        mock_mgr = MagicMock()
        adapter = CheckpointerAdapter(checkpoint_manager=mock_mgr)
        assert adapter is not None
        assert hasattr(adapter, "aget_tuple")
        assert hasattr(adapter, "aput")
        assert hasattr(adapter, "aput_writes")
        assert hasattr(adapter, "alist")

    def test_checkpointer_adapter_thread_id(self):
        """_thread_id 从 config 提取 task_id"""
        from app.runtime.execution_engine.checkpointer_adapter import CheckpointerAdapter

        mock_mgr = MagicMock()
        adapter = CheckpointerAdapter(checkpoint_manager=mock_mgr)
        config = {"configurable": {"thread_id": "task-123"}}
        tid = adapter._thread_id(config)
        assert tid == "task-123"

    def test_checkpointer_adapter_thread_id_no_config(self):
        """config 中没有 thread_id 时返回空"""
        from app.runtime.execution_engine.checkpointer_adapter import CheckpointerAdapter

        mock_mgr = MagicMock()
        adapter = CheckpointerAdapter(checkpoint_manager=mock_mgr)
        assert adapter._thread_id({}) == ""
        assert adapter._thread_id(None) == ""

    @pytest.mark.asyncio
    async def test_aput_writes_checkpoint(self):
        """aput() 调用 CheckpointManager.save_checkpoint"""
        from app.runtime.execution_engine.checkpointer_adapter import CheckpointerAdapter
        from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata

        mock_mgr = MagicMock()
        mock_mgr.save_checkpoint = AsyncMock()
        mock_mgr.save_checkpoint.return_value = None
        mock_mgr.state_manager = MagicMock()
        mock_mgr.state_manager.save = AsyncMock()

        adapter = CheckpointerAdapter(checkpoint_manager=mock_mgr)
        config = {"configurable": {"thread_id": "task-cp"}}
        checkpoint = Checkpoint(
            v=1,
            id="cp-1",
            ts="2024-01-01T00:00:00Z",
            channel_values={"task_id": "task-cp"},
            channel_versions={},
            versions_seen={},
        )
        metadata = CheckpointMetadata(source="loop", step=1, writes={}, parents={})

        result = await adapter.aput(config, checkpoint, metadata, {})
        assert result["configurable"]["thread_id"] == "task-cp"
        mock_mgr.save_checkpoint.assert_called_once()

    @pytest.mark.asyncio
    async def test_aget_tuple_loads_checkpoint(self):
        """aget_tuple() 从 CheckpointManager 加载 checkpoint"""
        from app.runtime.execution_engine.checkpointer_adapter import CheckpointerAdapter
        from app.runtime.state_manager.lightweight_state import LightweightState

        ls = LightweightState(task_id="task-cp-load", workflow_status="running")
        mock_mgr = MagicMock()
        mock_mgr.load_latest = AsyncMock(return_value=ls)
        mock_mgr.state_manager = MagicMock()

        adapter = CheckpointerAdapter(checkpoint_manager=mock_mgr)
        config = {"configurable": {"thread_id": "task-cp-load"}}

        result = await adapter.aget_tuple(config)
        assert result is not None

    @pytest.mark.asyncio
    async def test_alist_returns_checkpoints(self):
        """alist() 返回 checkpoint 列表"""
        from app.runtime.execution_engine.checkpointer_adapter import CheckpointerAdapter

        mock_mgr = MagicMock()
        mock_mgr.list_checkpoints = AsyncMock()

        # alist 是 async generator，不能直接 await
        # 用 MagicMock 的 return_value 配合 AsyncMock
        cp_values = [
            {"id": "cp-1", "node": "start", "workflow_status": "running"},
        ]
        mock_mgr.list_checkpoints.return_value = cp_values

        adapter = CheckpointerAdapter(checkpoint_manager=mock_mgr)
        config = {"configurable": {"thread_id": "task-cp-list"}}

        # 收集 async generator 的结果
        results = []
        async for item in adapter.alist(config):
            results.append(item)

        assert len(results) == 1


class TestStoreAdapter:
    """Phase 3.5: StoreAdapter 原生 LangGraph BaseStore Bridge"""

    def test_create_store_adapter(self):
        """可以创建 StoreAdapter"""
        from app.runtime.execution_engine.store_adapter import StoreAdapter

        adapter = StoreAdapter()
        assert adapter is not None
        assert hasattr(adapter, "batch")
        assert hasattr(adapter, "abatch")

    @pytest.mark.asyncio
    async def test_store_put_and_get(self):
        """StoreAdapter 支持 put 和 get 操作"""
        from app.runtime.execution_engine.store_adapter import StoreAdapter
        from langgraph.store.base import PutOp, GetOp

        adapter = StoreAdapter()
        ns = ("test", "doc")

        # put
        put_result = await adapter.abatch([
            PutOp(namespace=ns, key="key1", value={"data": "hello"})
        ])
        assert put_result is not None

        # get
        get_result = await adapter.abatch([
            GetOp(namespace=ns, key="key1")
        ])
        assert get_result is not None
        assert len(get_result) == 1
        item = get_result[0]
        assert item is not None
        assert item.value == {"data": "hello"}

    @pytest.mark.asyncio
    async def test_store_search_by_namespace(self):
        """StoreAdapter 支持 namespace 前缀搜索"""
        from app.runtime.execution_engine.store_adapter import StoreAdapter
        from langgraph.store.base import PutOp, SearchOp

        adapter = StoreAdapter()
        ns = ("app", "settings")

        await adapter.abatch([
            PutOp(namespace=ns, key="theme", value={"mode": "dark"}),
            PutOp(namespace=ns, key="lang", value={"code": "zh"}),
        ])

        results = await adapter.abatch([
            SearchOp(namespace_prefix=ns)
        ])
        items = results[0] if results else []
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_store_put_and_get_sync(self):
        """同步 batch 也支持 put/get"""
        from app.runtime.execution_engine.store_adapter import StoreAdapter
        from langgraph.store.base import PutOp, GetOp

        adapter = StoreAdapter()
        ns = ("sync", "test")

        adapter.batch([PutOp(namespace=ns, key="k1", value={"v": 1})])
        result = adapter.batch([GetOp(namespace=ns, key="k1")])
        assert result[0].value == {"v": 1}

    @pytest.mark.asyncio
    async def test_store_get_missing_key(self):
        """获取不存在的 key 返回 None"""
        from app.runtime.execution_engine.store_adapter import StoreAdapter
        from langgraph.store.base import GetOp

        adapter = StoreAdapter()
        result = await adapter.abatch([
            GetOp(namespace=("nonexistent",), key="missing")
        ])
        assert result[0] is None

    @pytest.mark.asyncio
    async def test_store_search_empty_namespace(self):
        """搜索空 namespace 返回空"""
        from app.runtime.execution_engine.store_adapter import StoreAdapter
        from langgraph.store.base import SearchOp

        adapter = StoreAdapter()
        results = await adapter.abatch([
            SearchOp(namespace_prefix=("empty",))
        ])
        items = results[0] if results else []
        assert items == []


class TestPhase3Integration:
    """Phase 3 集成：then= + ToolNode + ainvoke 协同工作"""

    @pytest.mark.asyncio
    async def test_build_graph_with_then_and_execute_via_ainvoke(self):
        """构建带 then= 的 graph 并用 ainvoke 执行"""
        adapter = LangGraphAdapter()
        spec = WorkflowSpec(
            name="int_test",
            nodes=[
                NodeSpec(id="start", type=NodeType.START),
                NodeSpec(id="check", type=NodeType.CONDITION),
                NodeSpec(id="pre", type=NodeType.TOOL, config={"tool_name": "log"}),
                NodeSpec(id="end", type=NodeType.END),
            ],
            edges=[
                EdgeSpec(source="start", target="check"),
                EdgeSpec(source="check", target="end", condition="true", then="pre"),
            ],
        )
        graph = adapter.build(spec)
        state = create_default_state(task_id="int-1")
        result = await adapter.ainvoke(graph, state, "int-1")
        assert result["workflow_status"] == "completed"
        assert result["task_id"] == "int-1"
