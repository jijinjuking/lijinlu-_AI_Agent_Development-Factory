"""
LangGraph Adapter — 动态 Workflow 构建与执行引擎

核心职责：
1. JSON WorkflowSpec → LangGraph StateGraph → CompiledGraph
2. astream() 执行 graph，发布 Event Bus 事件，写 Checkpoint

与各组件的关系：
- NodeExecutor → 实际执行每个节点的逻辑
- EventBus → 发布 WORKFLOW_NODE_ENTERED / WORKFLOW_NODE_EXITED
- CheckpointManager → 每个节点执行后自动写 Checkpoint
- InterruptHandler → human_approval 节点使用 LangGraph interrupt()

设计原则（架构文档第十章）：
- LangGraph 是 Runtime Orchestration Layer，不是流程图工具
- 禁止 graph.add_edge() 写死大量业务流程
- Workflow 从 JSON spec 动态构建
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Callable, Optional, Sequence, TYPE_CHECKING

from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt, Command, Send, StreamMode, StreamWriter

if TYPE_CHECKING:
    from langgraph.runtime import Runtime as LangGraphRuntime

from app.core.event_bus import Event, event_bus
from app.core.event_types import EventType
from app.runtime.checkpoint_manager.checkpoint_manager import CheckpointManager
from app.runtime.execution_engine.checkpointer_adapter import CheckpointerAdapter
from app.runtime.execution_engine.interrupt_handler import (
    InterruptHandler,
    interrupt_handler as _default_ih,
)
from app.runtime.execution_engine.node_executor import NodeExecutor
from app.runtime.execution_engine.runtime_context import RuntimeContext, create_runtime_context
from app.runtime.execution_engine.workflow_schema import (
    EdgeSpec,
    EdgeType,
    NodeDefaults,
    NodeSpec,
    NodeType,
    WorkflowSpec,
    WorkflowState,
    create_default_state,
    workflow_state_to_lightweight,
)
from app.runtime.state_manager.lightweight_state import LightweightState

logger = logging.getLogger("ai_runtime_os.langgraph_adapter")

# 特殊的节点名（LangGraph 入口/出口）
START_NODE = "__start__"
END_NODE = "__end__"


class LangGraphAdapter:
    """
    LangGraph 适配器 — 将 WorkflowSpec 编译为可执行的 CompiledGraph。

    用法：
        adapter = LangGraphAdapter(node_executor, checkpoint_mgr)
        graph = adapter.build(workflow_spec)
        async for event in adapter.astream(graph, initial_state, task_id):
            ...
    """

    def __init__(
        self,
        node_executor: Optional[NodeExecutor] = None,
        checkpoint_manager: Optional[CheckpointManager] = None,
        interrupt_handler: Optional[InterruptHandler] = None,
        context_schema: Optional[type] = None,
        checkpointer_adapter: Optional[CheckpointerAdapter] = None,
        tool_classes: Optional[dict[str, Any]] = None,
    ):
        """
        Args:
            node_executor: 节点执行器
            checkpoint_manager: checkpoint 管理器
            interrupt_handler: 中断处理器
            context_schema: LangGraph context_schema 类型（如 RuntimeContext），
                           设置后节点可通过 runtime: Runtime[Context] 参数获取运行时上下文
            checkpointer_adapter: LangGraph 原生 CheckpointerAdapter（Phase 3.3），
                                  设置后 build() 自动注入 checkpointer，支持 aget_state() 等 API
            tool_classes: 工具名 → LangChain BaseTool/Callable 映射，
                         用于 ToolNode（Phase 3.6）自动创建 langgraph.prebuilt.ToolNode
        """
        self.executor = node_executor or NodeExecutor()
        self.checkpoint_mgr = checkpoint_manager
        self.interrupts = interrupt_handler or _default_ih
        self.context_schema = context_schema
        self.checkpointer_adapter = checkpointer_adapter
        self.tool_classes = tool_classes or {}

    # ═══════════════════════════════════════
    # Build: WorkflowSpec → CompiledGraph
    # ═══════════════════════════════════════

    def build(self, spec: WorkflowSpec) -> CompiledStateGraph:
        """
        将 WorkflowSpec 编译为 LangGraph CompiledStateGraph。

        步骤：
        1. 创建 StateGraph(WorkflowState)
        2. 为每个节点注册 node function
        3. 添加边（直接边 / 条件边）
        4. 设置入口和出口
        5. compile()

        Args:
            spec: 工作流 JSON 定义

        Returns:
            编译后的 LangGraph CompiledStateGraph
        """
        logger.info("Building graph: name=%s nodes=%d edges=%d context_schema=%s",
                    spec.name, len(spec.nodes), len(spec.edges),
                    self.context_schema.__name__ if self.context_schema else None)

        # 1. 创建 StateGraph（可选 context_schema）
        sg_kwargs: dict[str, Any] = {}
        if self.context_schema is not None:
            sg_kwargs["context_schema"] = self.context_schema
        builder = StateGraph(WorkflowState, **sg_kwargs)

        # 2. 注册节点
        for node_spec in spec.nodes:
            handler = self._make_node_handler(node_spec, spec)
            builder.add_node(node_spec.id, handler)

        # 2.5 全局节点默认策略（P0: set_node_defaults）
        if spec.node_defaults:
            kwargs = {}
            rp = spec.node_defaults.to_retry_policy()
            if rp:
                kwargs["retry_policy"] = rp
            cp = spec.node_defaults.to_cache_policy()
            if cp:
                kwargs["cache_policy"] = cp
            if spec.node_defaults.timeout_seconds is not None:
                kwargs["timeout"] = spec.node_defaults.timeout_seconds
            if kwargs:
                builder.set_node_defaults(**kwargs)
                logger.info("Node defaults set: retry=%s cache=%s timeout=%s",
                            rp is not None, cp is not None, spec.node_defaults.timeout_seconds)

        # 3. 添加边（按类型分组处理）
        # direct 边: 无条件跳转
        direct_edges = [e for e in spec.edges if e.effective_type == EdgeType.DIRECT]
        for edge_spec in direct_edges:
            self._add_direct_edge(builder, edge_spec)

        # conditional 边: 按 source 聚合，每个 source 只调用一次 add_conditional_edges
        cond_edges = [e for e in spec.edges if e.effective_type == EdgeType.CONDITIONAL]
        sources_with_cond: set[str] = {e.source for e in cond_edges}
        for source_id in sources_with_cond:
            source_cond_edges = [e for e in cond_edges if e.source == source_id]
            source_direct_edges = [e for e in direct_edges if e.source == source_id]
            self._add_conditional_edges_for_source(builder, source_id, source_cond_edges, source_direct_edges)

        # send 边: 动态并行分发
        send_edges = [e for e in spec.edges if e.effective_type == EdgeType.SEND]
        for se in send_edges:
            self._add_send_edge(builder, se, spec)

        # 4. 设置入口
        entry_id = spec.get_entry_node_id()
        builder.set_entry_point(entry_id)
        logger.debug("Entry point: %s", entry_id)

        # 5. 处理孤立节点 — END 类型或没有出边的节点 → 连到 END
        for node_spec in spec.nodes:
            out_edges = spec.get_outgoing_edges(node_spec.id)
            if not out_edges and node_spec.type == NodeType.END:
                builder.add_edge(node_spec.id, END)

        # 6. Compile（传入中断配置 + checkpointer）
        compile_kwargs = {}
        if self.checkpointer_adapter is not None:
            compile_kwargs["checkpointer"] = self.checkpointer_adapter
        if spec.interrupt_before:
            compile_kwargs["interrupt_before"] = spec.interrupt_before
        if spec.interrupt_after:
            compile_kwargs["interrupt_after"] = spec.interrupt_after
        compiled = builder.compile(**compile_kwargs) if compile_kwargs else builder.compile()
        logger.info("Graph compiled: name=%s checkpointer=%s interrupt_before=%s interrupt_after=%s",
                    spec.name, compiled.checkpointer is not None,
                    spec.interrupt_before, spec.interrupt_after)
        return compiled

    # ═══════════════════════════════════════
    # Execute: CompiledGraph → AsyncIterator of events
    # ═══════════════════════════════════════

    async def astream(
        self,
        graph: CompiledStateGraph,
        initial_state: WorkflowState | LightweightState,
        task_id: str,
        config: dict[str, Any] | None = None,
        *,
        stream_mode: StreamMode | Sequence[StreamMode] | None = None,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        异步流式执行 graph，逐节点 yield 事件。

        Args:
            graph: 编译后的 LangGraph graph
            initial_state: 初始状态（WorkflowState 或 LightweightState）
            task_id: 任务 ID
            config: LangGraph RunnableConfig（含 callbacks 等）
            stream_mode: LangGraph stream_mode（一个或多个）。
                         - None (默认): v1 向后兼容模式，yield 节点事件
                         - "values": 每次状态更新后的完整 state
                         - "updates": 每次节点返回的增量更新
                         - "messages": LLM 消息 token 级别流式
                         - "custom": StreamWriter 写入的自定义数据
                         - "checkpoints": checkpoint 创建事件
                         - "tasks": PregelTask 生命周期事件
                         - "debug": checkpoint + tasks 组合调试事件
            context: LangGraph runtime context（对应 context_schema 定义的数据）

        Yields:
            stream_mode=None 时（v1）:
            {
                "event": "node_entered" | "node_exited" | "interrupted" | "completed" | "error",
                "node_id": str,
                "state": WorkflowState,
                ...
            }

            stream_mode 指定时（v2）:
            {
                "event": "state_updated" | "node_completed" | "token_stream"
                       | "custom_stream" | "checkpoint_created" | "task_lifecycle"
                       | "debug_info",
                "task_id": str,
                ...
            }
        """
        # 转换 state
        if isinstance(initial_state, LightweightState):
            from app.runtime.execution_engine.workflow_schema import lightweight_to_workflow_state
            state = lightweight_to_workflow_state(initial_state)
        else:
            state = dict(initial_state)

        state["task_id"] = task_id
        state["workflow_status"] = "running"

        run_config = {"configurable": {"task_id": task_id}, **(config or {})}

        # 发布 TASK_STARTED
        await event_bus.publish(Event(
            type=EventType.TASK_STARTED,
            task_id=task_id,
            payload={"state_summary": f"nodes={state.get('current_node', '')}",
                     "stream_mode": stream_mode},
            produced_by="langgraph_adapter",
        ))

        try:
            if stream_mode is not None:
                # ── v2 流式模式: 7 种 stream_mode 分发 ──
                # 单 mode: chunk 是 StreamPart dict {"type": "...", "data": ...}
                # 多 mode: chunk 是 (mode_name, data) 元组
                async for chunk in graph.astream(
                    state, run_config, stream_mode=stream_mode, context=context,
                    version="v2",
                ):
                    for event in self._dispatch_stream_chunk(chunk, task_id, state, stream_mode):
                        yield event

                # 正常完成
                state["workflow_status"] = "completed"
                await event_bus.publish(Event(
                    type=EventType.TASK_COMPLETED,
                    task_id=task_id,
                    payload={"final_node": state.get("current_node", "")},
                    produced_by="langgraph_adapter",
                ))
                yield {
                    "event": "completed",
                    "state": dict(state),
                    "total_tokens": state.get("total_tokens", 0),
                    "total_cost": state.get("total_cost", 0.0),
                    "llm_call_count": state.get("llm_call_count", 0),
                }
            else:
                # ── v1 向后兼容模式 ──
                async for chunk in graph.astream(state, run_config):
                    for node_id, node_state in chunk.items():
                        # 合并 state（LangGraph 只返回更新的字段）
                        if isinstance(node_state, dict):
                            state.update(node_state)

                        # 发布节点事件
                        event_data = {
                            "event": "node_exited",
                            "node_id": node_id,
                            "state": dict(state),
                            "workflow_status": state.get("workflow_status", "running"),
                        }
                        yield event_data

                        # 写 Checkpoint（如果配置了 CheckpointManager）
                        if self.checkpoint_mgr:
                            await self._save_checkpoint(task_id, state)

                        # 检查是否需要中断
                        if state.get("workflow_status") == "waiting_approval":
                            yield {
                                "event": "interrupted",
                                "node_id": node_id,
                                "message": state.get("metadata", {}).get("approval_message", ""),
                                "state": dict(state),
                            }
                            return  # 中断后停止 yield

                # 正常完成
                state["workflow_status"] = "completed"
                await event_bus.publish(Event(
                    type=EventType.TASK_COMPLETED,
                    task_id=task_id,
                    payload={"final_node": state.get("current_node", "")},
                    produced_by="langgraph_adapter",
                ))

                yield {
                    "event": "completed",
                    "state": dict(state),
                    "total_tokens": state.get("total_tokens", 0),
                    "total_cost": state.get("total_cost", 0.0),
                    "llm_call_count": state.get("llm_call_count", 0),
                }

        except Exception as e:
            logger.exception("Graph execution failed for task %s", task_id)
            state["workflow_status"] = "failed"
            state.setdefault("metadata", {})["error"] = str(e)

            await event_bus.publish(Event(
                type=EventType.TASK_FAILED,
                task_id=task_id,
                payload={"error": str(e)},
                produced_by="langgraph_adapter",
            ))

            yield {
                "event": "error",
                "error": str(e),
                "state": dict(state),
            }

    # ═══════════════════════════════════════
    # Resume: 从中断恢复执行
    # ═══════════════════════════════════════

    async def resume(
        self,
        graph: CompiledStateGraph,
        task_id: str,
        approved: bool,
        reason: str = "",
        config: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        从 human_approval 中断恢复执行。

        Args:
            graph: 原始编译后的 graph
            task_id: 任务 ID
            approved: True = 批准继续, False = 拒绝
            reason: 审批理由
            config: LangGraph 配置
        """
        # 更新中断状态
        self.interrupts.resume_with_approval(task_id, approved, reason)

        # 加载最新 checkpoint 获取 state
        state: WorkflowState = create_default_state(task_id=task_id)
        if self.checkpoint_mgr:
            try:
                latest_cp = await self.checkpoint_mgr.load_latest(task_id)
                if latest_cp:
                    from app.runtime.execution_engine.workflow_schema import lightweight_to_workflow_state
                    ls = LightweightState.from_dict(latest_cp.state_snapshot)
                    state = lightweight_to_workflow_state(ls)
            except Exception as e:
                logger.warning("Failed to load checkpoint for resume: %s", e)

        state["approval_result"] = approved
        state["approval_needed"] = False
        state["workflow_status"] = "running"

        run_config = {"configurable": {"task_id": task_id}, **(config or {})}

        # 重新 stream（LangGraph 会从中断点继续）
        async for event_data in self.astream(graph, state, task_id, run_config):
            yield event_data

    # ═══════════════════════════════════════
    # 内部: 节点处理器工厂
    # ═══════════════════════════════════════

    def _make_node_handler(self, node_spec: NodeSpec, spec: WorkflowSpec):
        """
        为节点创建 LangGraph node function。

        节点函数签名:
            (state: WorkflowState, config: RunnableConfig, *,
             writer: StreamWriter, runtime: Runtime[ContextT]) -> WorkflowState | Command

        - writer: LangGraph 自动注入，stream_mode="custom" 时可用
        - runtime: 当 StateGraph 设置了 context_schema 时自动注入

        支持 ToolNode（Phase 3.6）：
        - 如果 node_spec 是 TOOL 类型且 config.use_tool_node=true，
          自动从 tool_classes 查找工具并创建 langgraph.prebuilt.ToolNode
        - ToolNode 从 messages 中提取 tool_calls 并执行对应工具
        """
        # ── ToolNode 模式（Phase 3.6） ──
        if node_spec.type == NodeType.TOOL and node_spec.config.get("use_tool_node"):
            return self._make_tool_node_handler(node_spec)

        executor = self.executor
        interrupts = self.interrupts

        async def _all_node(
            state: WorkflowState,
            *,
            writer: Optional[StreamWriter] = None,
            runtime: Any = None,
        ):
            """统一入口：所有节点都经过 NodeExecutor.execute_node()

            支持两种返回：
            - dict: 状态更新（合并到 state）
            - Command: LangGraph 原生 Command（goto/update/resume）
            """
            result = await executor.execute_node(node_spec, state, writer=writer)
            if isinstance(result, Command):
                return result
            return result

        async def _human_approval_node(
            state: WorkflowState,
            *,
            writer: Optional[StreamWriter] = None,
            runtime: Any = None,
        ):
            # 先执行节点逻辑（设置 approval_needed = True）
            result = await executor.execute_node(node_spec, state, writer=writer)

            # 如果 executor 返回了 Command（goto/update），直接透传
            if isinstance(result, Command):
                return result

            state = result

            # 创建中断请求
            message = node_spec.config.get("message", "请确认是否继续执行")
            timeout = node_spec.config.get("timeout_seconds", 300)
            interrupts.request_approval(
                task_id=state.get("task_id", ""),
                node_id=node_spec.id,
                message=message,
                timeout_seconds=timeout,
            )

            # LangGraph interrupt: 暂停执行，等待外部恢复
            decision = interrupt({
                "type": "human_approval",
                "node_id": node_spec.id,
                "message": message,
                "task_id": state.get("task_id", ""),
            })

            # 恢复后: Command(resume=...) / Command(update=...) / 直接返回 state
            if isinstance(decision, Command):
                return decision
            elif isinstance(decision, dict):
                # 中断恢复后，decision 可能是 dict（更新的字段）
                state["workflow_status"] = "running"
                state["approval_needed"] = False
                state["approval_result"] = True
                state.update(decision)
                return state
            else:
                state["workflow_status"] = "running"
                state["approval_needed"] = False
                state["approval_result"] = True
                return state

        handler_map = {
            NodeType.TOOL: _all_node,
            NodeType.LLM: _all_node,
            NodeType.CONDITION: _all_node,
            NodeType.HUMAN_APPROVAL: _human_approval_node,
            NodeType.START: _all_node,
            NodeType.END: _all_node,
        }

        return handler_map.get(node_spec.type, _all_node)

    def _make_tool_node_handler(self, node_spec: NodeSpec):
        """
        创建 langgraph.prebuilt.ToolNode 包装的节点处理器。

        ToolNode 工作方式：
        - 从 state["messages"] 中提取最后一条 AIMessage 的 tool_calls
        - 对每个 tool_call 查找对应工具并执行
        - 返回 {"messages": [ToolMessage, ...]}

        config 支持的字段：
        - tools: list[str] — 工具名列表（从 tool_classes 查找）
        - handle_tool_errors: bool|str — 错误处理策略
        - messages_key: str — state 中消息字段名，默认 "messages"
        """
        tool_names: list[str] = node_spec.config.get("tools", [])
        if not tool_names or not self.tool_classes:
            # 回退：没有工具映射时，走普通 _all_node 路径
            logger.warning(
                "ToolNode requested for '%s' but no tool_classes configured, falling back",
                node_spec.id,
            )
            executor = self.executor

            async def _fallback(state: WorkflowState, *, writer=None, runtime=None):
                result = await executor.execute_node(node_spec, state, writer=writer)
                if isinstance(result, Command):
                    return result
                return result
            return _fallback

        # 从 tool_classes 查找工具
        tools = []
        for name in tool_names:
            if name in self.tool_classes:
                tools.append(self.tool_classes[name])
            else:
                logger.warning("ToolNode: tool '%s' not found in tool_classes, skipping", name)

        if not tools:
            logger.warning("ToolNode for '%s': no valid tools found", node_spec.id)
            executor = self.executor

            async def _no_tools(state: WorkflowState, *, writer=None, runtime=None):
                result = await executor.execute_node(node_spec, state, writer=writer)
                if isinstance(result, Command):
                    return result
                return result
            return _no_tools

        # 创建 ToolNode
        handle_errors = node_spec.config.get("handle_tool_errors", True)
        messages_key = node_spec.config.get("messages_key", "messages")
        tool_node = ToolNode(
            tools,
            name=node_spec.id,
            handle_tool_errors=handle_errors,
            messages_key=messages_key,
        )

        logger.info(
            "ToolNode created for '%s': tools=%s messages_key=%s",
            node_spec.id, tool_names, messages_key,
        )

        async def _tool_node_handler(
            state: WorkflowState,
            *,
            writer: Optional[StreamWriter] = None,
            runtime: Any = None,
        ):
            """LangGraph ToolNode 包装器。

            将 WorkflowState 转为 dict 发给 ToolNode.ainvoke()，
            结果合并回 state 返回。
            """
            try:
                result = await tool_node.ainvoke(dict(state))
                if isinstance(result, dict):
                    # ToolNode 返回 {"messages": [ToolMessage, ...]}
                    state.update(result)
                return state
            except Exception as e:
                logger.exception("ToolNode execution failed for '%s': %s", node_spec.id, e)
                state.setdefault("metadata", {})["tool_node_error"] = str(e)
                return state

        return _tool_node_handler

    # ═══════════════════════════════════════
    # 内部: 边处理器
    # ═══════════════════════════════════════

    def _add_direct_edge(self, builder: StateGraph, edge: EdgeSpec) -> None:
        """添加直接边"""
        target = edge.target if edge.target else END
        builder.add_edge(edge.source, target)

    def _add_conditional_edges_for_source(
        self,
        builder: StateGraph,
        source_id: str,
        cond_edges: list[EdgeSpec],
        direct_edges: list[EdgeSpec],
    ) -> None:
        """
        为一个 source 节点的所有条件边构建路由。

        LangGraph 限制：每个 source 只能调用一次 add_conditional_edges。
        因此需要把同一个 source 的所有条件逻辑合并到一个路由函数中。

        路由逻辑：
        - 评估第一个条件边的表达式（通过 state.metadata.condition_results[node_id]）
        - 为真 → 走对应 target（如果设置了 then，先走 then 再走 target）
        - 为假 → 走默认（第一条直接边或 END）
        - 多条件边：按顺序评估，命中即返回

        支持 EdgeSpec.then：
        - then="X" 且 target="Y" → 条件满足时 router 返回 X，并添加 X→Y 直连边
        - 实现"A→(条件通过)→X→Y"的必经中间节点语义
        """
        default_target = direct_edges[0].target if direct_edges else END

        # 为所有设置了 then 的边添加 then→target 直连边
        for ce in cond_edges:
            if ce.then and ce.target:
                builder.add_edge(ce.then, ce.target)
                logger.debug("then= edge: %s → %s → %s", ce.source, ce.then, ce.target)

        if len(cond_edges) == 1:
            # 单条件边
            target = cond_edges[0].target
            then_node = cond_edges[0].then

            def _single_router(state: WorkflowState) -> str:
                cond_results = state.get("metadata", {}).get("condition_results", {})
                result = cond_results.get(source_id, False)
                if result:
                    return then_node if then_node else target
                return default_target

            _single_router.__name__ = f"_router_{source_id}"
            builder.add_conditional_edges(source_id, _single_router)
        else:
            # 多条件边：按顺序评估
            def _multi_router(state: WorkflowState) -> str:
                cond_results = state.get("metadata", {}).get("condition_results", {})
                for ce in cond_edges:
                    val = cond_results.get(source_id, False)
                    result = val if ce.condition == "true" else not val
                    if result:
                        return ce.then if ce.then else ce.target
                return default_target

            _multi_router.__name__ = f"_router_{source_id}"
            builder.add_conditional_edges(source_id, _multi_router)

    def _add_send_edge(
        self,
        builder: StateGraph,
        edge: EdgeSpec,
        spec: WorkflowSpec,
    ) -> None:
        """
        添加动态并行分发边（Send）。

        Send 边的工作原理：
        - 从 state 中按 items_expr 提取列表
        - 为列表每一项创建 Send(send_node, {item_key: item})
        - LangGraph 自动并行执行所有分支

        Example:
            EdgeSpec(
                source="fan_out", target="", edge_type=EdgeType.SEND,
                send_node="process_item",
                items_expr="state.items",
            )
        """
        send_node = edge.send_node
        if not send_node:
            logger.warning("Send edge from '%s' has no send_node, skipping", edge.source)
            return

        items_expr = edge.items_expr or "state.items"

        def _send_router(state: WorkflowState):
            """根据 items_expr 从 state 提取列表，返回 Send 列表"""
            # 安全求值 items_expr
            items = _eval_items_expr(items_expr, state)
            if not isinstance(items, list):
                logger.warning("Send edge: items_expr '%s' did not return a list, got %s", items_expr, type(items))
                return [send_node]  # 兜底：作为普通边

            sends = [Send(send_node, {"item": item}) for item in items]
            logger.debug("Send edge: fanning out %d items to node '%s'", len(sends), send_node)
            return sends

        _send_router.__name__ = f"_send_{edge.source}"
        builder.add_conditional_edges(edge.source, _send_router)

    # ═══════════════════════════════════════
    # 内部: Stream chunk 分发
    # ═══════════════════════════════════════

    def _dispatch_stream_chunk(
        self,
        chunk: Any,
        task_id: str,
        state: dict[str, Any],
        stream_mode: Any = None,
    ):
        """
        将 LangGraph v2 流式 chunk 分发为统一事件格式。

        支持两种 chunk 格式：
        1. 单 mode (stream_mode 是字符串): chunk 是 StreamPart dict
           {"type": "values"|"updates"|..., "ns": [...], "data": ...}
        2. 多 mode (stream_mode 是序列): chunk 是 (mode_name, data) 元组
        """
        # 多 mode: chunk 是 (mode_name, data) 元组
        if isinstance(chunk, tuple) and len(chunk) == 2:
            mode, data = chunk
            yield from self._dispatch_single_part(mode, data, task_id, state)
        # 单 mode: chunk 是 StreamPart dict
        elif isinstance(chunk, dict):
            part_type = chunk.get("type", "")
            yield from self._dispatch_single_part(
                part_type, chunk.get("data"), task_id, state,
                ns=chunk.get("ns", ()),
            )
        else:
            logger.debug("Unknown stream chunk format: %s", type(chunk))

    def _dispatch_single_part(
        self,
        part_type: str,
        data: Any,
        task_id: str,
        state: dict[str, Any],
        ns: tuple = (),
    ):
        """
        分发单个 stream part。

        映射关系:
        - values     → state_updated (完整状态快照)
        - updates    → node_completed (节点增量更新)
        - messages   → token_stream (LLM token 流)
        - custom     → custom_stream (StreamWriter 写入)
        - checkpoints → checkpoint_created
        - tasks      → task_lifecycle
        - debug      → debug_info
        """
        if part_type == "values":
            if isinstance(data, dict):
                state.update(data)
            yield {
                "event": "state_updated",
                "task_id": task_id,
                "state": dict(state) if isinstance(data, dict) else data,
                "ns": ns,
            }

        elif part_type == "updates":
            if isinstance(data, dict):
                for node_id, update in data.items():
                    if isinstance(update, dict):
                        state.update(update)
                    yield {
                        "event": "node_completed",
                        "node_id": node_id,
                        "update": update,
                        "task_id": task_id,
                        "ns": ns,
                    }

        elif part_type == "messages":
            message = data[0] if isinstance(data, tuple) and len(data) > 0 else None
            metadata = data[1] if isinstance(data, tuple) and len(data) > 1 else {}
            yield {
                "event": "token_stream",
                "message": message,
                "metadata": metadata,
                "task_id": task_id,
                "ns": ns,
            }

        elif part_type == "custom":
            yield {
                "event": "custom_stream",
                "data": data,
                "task_id": task_id,
                "ns": ns,
            }

        elif part_type == "checkpoints":
            yield {
                "event": "checkpoint_created",
                "data": data,
                "task_id": task_id,
                "ns": ns,
            }

        elif part_type == "tasks":
            yield {
                "event": "task_lifecycle",
                "data": data,
                "task_id": task_id,
                "ns": ns,
            }

        elif part_type == "debug":
            yield {
                "event": "debug_info",
                "data": data,
                "task_id": task_id,
                "ns": ns,
            }

    async def _save_checkpoint(self, task_id: str, state: WorkflowState) -> None:
        """将当前 state 写入 CheckpointManager"""
        if not self.checkpoint_mgr:
            return
        try:
            lightweight = workflow_state_to_lightweight(state)
            await self.checkpoint_mgr.state_manager.save(task_id, lightweight)
            await self.checkpoint_mgr.save_checkpoint(task_id)
        except Exception as e:
            logger.warning("Checkpoint save failed for task %s: %s", task_id, e)

    # ═══════════════════════════════════════
    # CompiledStateGraph API 暴露（Phase 3.7）
    # ═══════════════════════════════════════

    async def ainvoke(
        self,
        graph: CompiledStateGraph,
        initial_state: WorkflowState | LightweightState | dict[str, Any],
        task_id: str,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        同步式异步执行 graph 到完成，返回最终 state。

        对应 LangGraph CompiledStateGraph.ainvoke()。

        Args:
            graph: 编译后的 LangGraph graph
            initial_state: 初始状态
            task_id: 任务 ID
            config: LangGraph RunnableConfig

        Returns:
            最终的 WorkflowState dict
        """
        state = dict(initial_state) if not isinstance(initial_state, dict) else initial_state
        state["task_id"] = task_id
        state["workflow_status"] = "running"

        run_config = {"configurable": {"task_id": task_id}, **(config or {})}

        await event_bus.publish(Event(
            type=EventType.TASK_STARTED,
            task_id=task_id,
            payload={"invoke_mode": "ainvoke"},
            produced_by="langgraph_adapter",
        ))

        try:
            result = await graph.ainvoke(state, run_config)
            result["workflow_status"] = "completed"

            await event_bus.publish(Event(
                type=EventType.TASK_COMPLETED,
                task_id=task_id,
                payload={"final_node": result.get("current_node", "")},
                produced_by="langgraph_adapter",
            ))
            return dict(result)
        except Exception as e:
            logger.exception("ainvoke failed for task %s", task_id)

            await event_bus.publish(Event(
                type=EventType.TASK_FAILED,
                task_id=task_id,
                payload={"error": str(e)},
                produced_by="langgraph_adapter",
            ))
            raise

    async def aget_state(self, task_id: str) -> LightweightState | None:
        """
        获取任务的当前状态快照。

        对应 LangGraph CompiledStateGraph.aget_state(config)。

        优先级：
        1. 从 CheckpointManager 加载最新 state
        2. 返回 None（如果任务没有 checkpoint）

        Args:
            task_id: 任务 ID

        Returns:
            LightweightState 或 None
        """
        if self.checkpoint_mgr:
            try:
                latest = await self.checkpoint_mgr.load_latest(task_id)
                if latest:
                    return latest
            except Exception as e:
                logger.warning("aget_state failed for task %s: %s", task_id, e)
        return None

    async def aupdate_state(
        self,
        task_id: str,
        values: dict[str, Any],
    ) -> bool:
        """
        更新任务的状态。

        对应 LangGraph CompiledStateGraph.aupdate_state(config, values)。

        修改当前 state 后自动创建新 checkpoint。

        Args:
            task_id: 任务 ID
            values: 要更新的字段（会合并到现有 state）

        Returns:
            True 如果更新成功
        """
        if not self.checkpoint_mgr:
            logger.warning("aupdate_state: no CheckpointManager configured")
            return False

        try:
            # 加载当前 state
            current = await self.checkpoint_mgr.load_latest(task_id)
            if current:
                current_dict = current.to_dict()
                current_dict.update(values)
                await self.checkpoint_mgr.state_manager.save(
                    task_id,
                    LightweightState.from_dict(current_dict),
                )
            else:
                # 没有现有 state: 创建新的
                ls = LightweightState(task_id=task_id, **values)
                await self.checkpoint_mgr.state_manager.save(task_id, ls)

            # 写 checkpoint
            await self.checkpoint_mgr.save_checkpoint(task_id)
            logger.info("aupdate_state: task %s updated with %d fields", task_id, len(values))
            return True
        except Exception as e:
            logger.exception("aupdate_state failed for task %s: %s", task_id, e)
            return False

    async def aget_state_history(
        self,
        task_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        获取任务的 checkpoint 历史。

        对应 LangGraph CompiledStateGraph.aget_state_history(config)。

        Args:
            task_id: 任务 ID
            limit: 最大返回条数

        Returns:
            checkpoint 列表，每条包含 checkpoint_id, created_at, state_snapshot
        """
        if not self.checkpoint_mgr:
            return []

        try:
            cps = await self.checkpoint_mgr.list_checkpoints(task_id, limit=limit)
            result = []
            for cp in cps:
                result.append({
                    "checkpoint_id": getattr(cp, "checkpoint_id", ""),
                    "created_at": str(getattr(cp, "created_at", "")),
                    "state_snapshot": getattr(cp, "state_snapshot", {}),
                })
            return result
        except Exception as e:
            logger.warning("aget_state_history failed for task %s: %s", task_id, e)
            return []

    # ═══════════════════════════════════════
    # Quick API: 一步构建并执行
    # ═══════════════════════════════════════

    async def run_workflow(
        self,
        spec: WorkflowSpec,
        task_id: str,
        initial_state: WorkflowState | LightweightState | None = None,
        goal: str = "",
        project_id: str = "",
        *,
        stream_mode: StreamMode | Sequence[StreamMode] | None = None,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        一步式 API：build + astream。

        Args:
            spec: 工作流定义
            task_id: 任务 ID
            initial_state: 可选初始状态
            goal: 任务目标
            project_id: 项目 ID
            stream_mode: LangGraph stream_mode（可选）
            context: LangGraph runtime context（可选）

        Yields:
            执行事件流
        """
        state = initial_state or create_default_state(
            task_id=task_id,
            project_id=project_id,
            goal=goal,
        )
        graph = self.build(spec)
        async for event in self.astream(
            graph, state, task_id,
            stream_mode=stream_mode, context=context,
        ):
            yield event


# ═══════════════════════════════════════════
# 内部: 表达式求值辅助
# ═══════════════════════════════════════════

def _eval_items_expr(expr: str, state: WorkflowState) -> Any:
    """
    安全求值 items 表达式。

    支持的语法：
    - "state.items" → state["items"]
    - "state.metadata.files" → state["metadata"]["files"]
    - "[]" → 空列表

    安全限制：只支持字典访问链，不执行任意代码。
    """
    expr = expr.strip()
    if not expr or expr == "[]":
        return []

    if expr.startswith("state."):
        path = expr[6:].split(".")
        current = state
        for key in path:
            if isinstance(current, dict):
                current = current.get(key, [])
            else:
                return []
        return current if isinstance(current, list) else []

    return []


# ═══════════════════════════════════════════
# 全局默认实例
# ═══════════════════════════════════════════

default_adapter = LangGraphAdapter()
