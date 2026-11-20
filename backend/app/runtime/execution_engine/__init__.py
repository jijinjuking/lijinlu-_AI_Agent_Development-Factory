"""
AI Runtime OS — Execution Engine (W7)

基于 LangGraph 的动态 Workflow 构建与执行引擎。

核心组件:
- LangGraphAdapter: JSON WorkflowSpec → CompiledGraph → astream()/ainvoke()/aget_state()
- NodeExecutor: 统一节点执行器 (llm / tool / condition / human_approval)
- InterruptHandler: 人机交互中断管理
- RuntimeContext: LangGraph context_schema 定义
- WorkflowSpec / WorkflowState: 类型定义
- CheckpointerAdapter: LangGraph 原生 BaseCheckpointSaver 桥接
- StoreAdapter: LangGraph 原生 BaseStore 桥接
"""
from app.runtime.execution_engine.langgraph_adapter import LangGraphAdapter, default_adapter
from app.runtime.execution_engine.node_executor import NodeExecutor, default_node_executor
from app.runtime.execution_engine.interrupt_handler import (
    InterruptHandler,
    InterruptRequest,
    interrupt_handler,
)
from app.runtime.execution_engine.runtime_context import (
    RuntimeContext,
    create_runtime_context,
)
from app.runtime.execution_engine.checkpointer_adapter import CheckpointerAdapter
from app.runtime.execution_engine.store_adapter import StoreAdapter
from app.runtime.execution_engine.workflow_schema import (
    # 类型
    WorkflowState,
    WorkflowSpec,
    NodeSpec,
    EdgeSpec,
    EdgeType,
    NodeDefaults,
    NodeType,
    # 工厂
    create_default_state,
    # 桥接
    workflow_state_to_lightweight,
    lightweight_to_workflow_state,
    # 示例
    EXAMPLE_WORKFLOW,
)

__all__ = [
    # Core
    "LangGraphAdapter",
    "NodeExecutor",
    "InterruptHandler",
    "InterruptRequest",
    # Adapters（Phase 3）
    "CheckpointerAdapter",
    "StoreAdapter",
    # Types
    "WorkflowState",
    "WorkflowSpec",
    "NodeSpec",
    "EdgeSpec",
    "EdgeType",
    "NodeDefaults",
    "NodeType",
    "RuntimeContext",
    # Factory
    "create_default_state",
    "create_runtime_context",
    "workflow_state_to_lightweight",
    "lightweight_to_workflow_state",
    # Defaults
    "default_adapter",
    "default_node_executor",
    "interrupt_handler",
    # Demo
    "EXAMPLE_WORKFLOW",
]
