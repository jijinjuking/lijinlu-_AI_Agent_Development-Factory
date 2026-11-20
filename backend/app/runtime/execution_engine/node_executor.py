"""
Node Executor — 统一节点执行器

LangGraph 图中每个节点的执行逻辑。支持四种节点类型：
- llm: 调用 LLM 服务，将结果写入 state
- tool: 委托给 ToolRuntime 执行工具
- condition: 执行条件表达式，决定路由
- human_approval: 设置中断标记

所有节点执行时自动发布 Event Bus 事件。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Union

from langgraph.types import Command, StreamWriter

from app.core.event_bus import Event, event_bus
from app.core.event_types import EventType
from app.runtime.execution_engine.workflow_schema import (
    NodeSpec,
    NodeType,
    WorkflowState,
)
from app.runtime.tool_runtime.executor import ToolExecutor, get_executor
from app.runtime.tool_runtime.models import (
    ExecutionContext,
    ExecutionStatus,
    PermissionLevel,
)

logger = logging.getLogger("ai_runtime_os.node_executor")


class NodeExecutor:
    """
    统一节点执行器。

    用法：
        executor = NodeExecutor(tool_executor, llm_callable)
        state = await executor.execute_node(node_spec, state)
    """

    def __init__(
        self,
        tool_executor: Optional[ToolExecutor] = None,
        llm_callable: Optional[
            Callable[[str, list[dict], dict[str, Any]], Any]
        ] = None,
    ):
        """
        Args:
            tool_executor: ToolRuntime 执行器实例
            llm_callable: LLM 调用函数签名 (system_prompt, messages, config) -> response
        """
        self.tool_executor = tool_executor or get_executor()
        self.llm_callable = llm_callable

    # ── 主分发 ──

    async def execute_node(
        self,
        node: NodeSpec,
        state: WorkflowState,
        writer: Optional[StreamWriter] = None,
    ):
        """
        根据节点类型分发到具体执行器。

        Args:
            node: 节点定义
            state: 当前 WorkflowState
            writer: 可选的 StreamWriter，用于推送自定义流式数据
                   当 LangGraph 以 stream_mode="custom" 执行时注入

        返回值:
        - WorkflowState: 正常状态更新（大多数情况）
        - Command: 动态路由/更新（当节点 config 中 dynamic_routing=true 时）

        Command 的用法:
        - Command(goto="node_id"): 动态跳转到指定节点（覆盖静态边）
        - Command(goto="node_id", update={"key": "val"}): 跳转同时更新状态
        - Command(update={"key": "val"}): 只更新状态（走正常条件边路由）
        """
        task_id = state.get("task_id", "")
        logger.debug("Executing node: type=%s id=%s task=%s", node.type, node.id, task_id)

        # 发布 NODE_ENTERED 事件
        await event_bus.publish(Event(
            type=EventType.WORKFLOW_NODE_ENTERED,
            task_id=task_id,
            payload={"node_id": node.id, "node_type": node.type.value, "node_label": node.label},
            produced_by="node_executor",
        ))

        # 更新 current_node
        state["current_node"] = node.id

        # 分发
        handler_map = {
            NodeType.LLM: self._execute_llm,
            NodeType.TOOL: self._execute_tool,
            NodeType.CONDITION: self._execute_condition,
            NodeType.HUMAN_APPROVAL: self._execute_human_approval,
            NodeType.START: self._execute_noop,
            NodeType.END: self._execute_noop,
        }

        handler = handler_map.get(node.type)
        if handler is None:
            logger.warning("Unknown node type: %s, skipping", node.type)
            return state

        try:
            state = await handler(node, state, writer=writer)
            # 记录步骤历史
            state.setdefault("steps", []).append({
                "node": node.id,
                "type": node.type.value,
                "outcome": "success",
                "detail": "",
            })
        except Exception as e:
            logger.exception("Node execution failed: id=%s type=%s", node.id, node.type)
            state["error_count"] = state.get("error_count", 0) + 1
            state.setdefault("steps", []).append({
                "node": node.id,
                "type": node.type.value,
                "outcome": "error",
                "detail": str(e),
            })

        # 发布 NODE_EXITED 事件
        await event_bus.publish(Event(
            type=EventType.WORKFLOW_NODE_EXITED,
            task_id=task_id,
            payload={
                "node_id": node.id,
                "node_type": node.type.value,
                "error_count": state.get("error_count", 0),
            },
            produced_by="node_executor",
        ))

        # 动态路由支持：检查节点 config 是否需要返回 Command
        dynamic_goto = node.config.get("goto")
        dynamic_update = node.config.get("update")
        if dynamic_goto or dynamic_update:
            cmd_kwargs = {}
            if dynamic_goto:
                cmd_kwargs["goto"] = dynamic_goto
            if dynamic_update:
                cmd_kwargs["update"] = dynamic_update
            logger.info("Node '%s' returning Command: %s", node.id, cmd_kwargs)
            return Command(**cmd_kwargs)

        return state

    # ── LLM 节点 ──

    async def _execute_llm(
        self,
        node: NodeSpec,
        state: WorkflowState,
        writer: Optional[StreamWriter] = None,
    ) -> WorkflowState:
        """执行 LLM 调用节点"""
        config = node.config
        system_prompt = config.get("system_prompt", "")

        if writer:
            writer({"type": "progress", "step": "calling_llm", "node_id": node.id, "node_label": node.label})

        if self.llm_callable is None:
            # 无 LLM callable 时的 fallback：写入模拟响应
            state.setdefault("messages", []).append({
                "role": "assistant",
                "content": f"[LLM node '{node.id}' executed with prompt: {system_prompt[:100]}]",
            })
            logger.info("LLM node '%s' executed (mock mode)", node.id)
        else:
            try:
                response = await self.llm_callable(
                    system_prompt,
                    list(state.get("messages", [])),
                    config,
                )
                state.setdefault("messages", []).append({
                    "role": "assistant",
                    "content": str(response),
                })
                # 更新 token 统计（如果 LLM callable 返回结构化数据）
                if isinstance(response, dict):
                    state["total_tokens"] = state.get("total_tokens", 0) + response.get("tokens", 0)
                    state["total_cost"] = state.get("total_cost", 0.0) + response.get("cost", 0.0)
                state["llm_call_count"] = state.get("llm_call_count", 0) + 1
                if writer:
                    writer({
                        "type": "progress",
                        "step": "llm_done",
                        "node_id": node.id,
                        "llm_call_count": state["llm_call_count"],
                    })
                logger.info("LLM node '%s' completed (total calls: %d)", node.id, state["llm_call_count"])
            except Exception as e:
                logger.exception("LLM call failed in node '%s'", node.id)
                state.setdefault("error_count", 0)
                state["error_count"] += 1
                state.setdefault("messages", []).append({
                    "role": "system",
                    "content": f"LLM call failed: {e}",
                })
                # 达到最大错误数，标记工作流失败
                max_errors = node.config.get("max_errors", 3)
                if state["error_count"] >= max_errors:
                    state["workflow_status"] = "failed"
                    logger.error(
                        "Workflow %s failed: error_count=%d >= max_errors=%d",
                        state.get("task_id", "unknown"),
                        state["error_count"],
                        max_errors,
                    )

        return state

    # ── Tool 节点 ──

    async def _execute_tool(
        self,
        node: NodeSpec,
        state: WorkflowState,
        writer: Optional[StreamWriter] = None,
    ) -> WorkflowState:
        """执行工具调用节点"""
        config = node.config
        tool_name = config.get("tool_name", "")
        args_template = config.get("args_template", {})

        if writer:
            writer({
                "type": "progress",
                "step": "calling_tool",
                "node_id": node.id,
                "tool_name": tool_name,
            })

        # 解析参数模板（用 state 中的值替换占位符）
        resolved_args = self._resolve_args_template(args_template, state)

        context = ExecutionContext(
            task_id=state.get("task_id"),
            permission_level=PermissionLevel.NORMAL,
            metadata={"node_id": node.id, "node_label": node.label},
        )

        result = await self.tool_executor.execute(tool_name, resolved_args, context)

        # 将工具执行结果写入 state
        if result.status == ExecutionStatus.COMPLETED:
            output_msg = result.output
        else:
            output_msg = f"Error: {result.error}"
            state["error_count"] = state.get("error_count", 0) + 1
        state.setdefault("messages", []).append({
            "role": "tool",
            "content": output_msg or "",
            "tool_call_id": f"tc_{state.get('task_id', 'unknown')}_{node.id}",
            "name": tool_name,
            "tool_name": tool_name,
            "status": result.status.value,
            "duration_ms": result.duration_ms,
        })

        # 如果有 artifact 产出，记录引用
        if result.metadata and "artifact_id" in result.metadata:
            state.setdefault("artifact_refs", []).append(result.metadata["artifact_id"])

        if writer:
            writer({
                "type": "progress",
                "step": "tool_done",
                "node_id": node.id,
                "tool_name": tool_name,
                "status": result.status.value,
                "duration_ms": result.duration_ms,
            })

        logger.info(
            "Tool node '%s' executed: tool=%s status=%s",
            node.id, tool_name, result.status.value,
        )

        return state

    # ── Condition 节点 ──

    async def _execute_condition(
        self,
        node: NodeSpec,
        state: WorkflowState,
        writer: Optional[StreamWriter] = None,
    ) -> WorkflowState:
        """
        执行条件节点。
        条件节点的路由逻辑在 graph 构建时通过 conditional_edges 实现，
        这里只记录条件评估日志，不修改路由。
        """
        expression = node.config.get("expression", "True")
        try:
            result = self._evaluate_expression(expression, state)
            state["metadata"].setdefault("condition_results", {})
            state["metadata"]["condition_results"][node.id] = result
            logger.debug("Condition node '%s' evaluated: %s → %s", node.id, expression, result)
        except Exception as e:
            logger.warning("Condition evaluation failed: node=%s expr=%s error=%s", node.id, expression, e)
            state["metadata"].setdefault("condition_results", {})
            state["metadata"]["condition_results"][node.id] = False

        return state

    # ── Human Approval 节点 ──

    async def _execute_human_approval(
        self,
        node: NodeSpec,
        state: WorkflowState,
        writer: Optional[StreamWriter] = None,
    ) -> WorkflowState:
        """
        设置人工审批中断标记。
        实际中断由 LangGraph interrupt() 在 graph 层面处理，
        这里只修改 state 标记。
        """
        state["approval_needed"] = True
        state["workflow_status"] = "waiting_approval"
        state.setdefault("metadata", {})["approval_node"] = node.id
        state.setdefault("metadata", {})["approval_message"] = node.config.get(
            "message", "请确认是否继续执行"
        )

        logger.info("Human approval requested at node '%s'", node.id)
        return state

    # ── No-op 节点 ──

    async def _execute_noop(
        self,
        node: NodeSpec,
        state: WorkflowState,
        writer: Optional[StreamWriter] = None,
    ) -> WorkflowState:
        """Start/End 节点：无操作，仅记录日志"""
        logger.debug("Noop node '%s' type=%s", node.id, node.type)
        return state

    # ── 辅助方法 ──

    def _resolve_args_template(
        self,
        template: dict[str, Any],
        state: WorkflowState,
    ) -> dict[str, Any]:
        """
        解析参数模板中的占位符。
        支持简单模式：{{ state.field }} → 替换为 state 中的值
        """
        resolved = {}
        for key, value in template.items():
            if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
                state_path = value[2:-2].strip()
                if state_path.startswith("state."):
                    field = state_path[6:]
                    resolved[key] = state.get(field, value)
                else:
                    resolved[key] = value
            elif isinstance(value, dict):
                resolved[key] = self._resolve_args_template(value, state)
            else:
                resolved[key] = value
        return resolved

    def _evaluate_expression(
        self,
        expression: str,
        state: WorkflowState,
    ) -> bool:
        """
        安全评估条件表达式。

        支持的表达式语法：
        - state.workflow_status == 'completed'
        - state.error_count > 0
        - state.metadata.condition_results.some_node == True
        - len(state.messages) > 3
        """
        # 构建安全的求值命名空间
        safe_builtins = {"True": True, "False": False, "len": len, "int": int, "str": str, "float": float}

        # 将 state 转为带属性访问的命名空间
        class StateProxy:
            def __init__(self, data: dict):
                self._data = data

            def __getattr__(self, name: str) -> Any:
                if name == "_data":
                    return object.__getattribute__(self, "_data")
                val = self._data.get(name)
                if val is None:
                    return val
                if isinstance(val, dict):
                    return StateProxy(val)
                return val

            def get(self, key: str, default: Any = None) -> Any:
                return self._data.get(key, default)

        namespace = {"state": StateProxy(dict(state)), **safe_builtins}

        try:
            result = eval(expression, {"__builtins__": {}}, namespace)
            return bool(result)
        except Exception:
            return False


# ═══════════════════════════════════════════
# 全局默认实例
# ═══════════════════════════════════════════

default_node_executor = NodeExecutor()
