"""
Workflow Schema — LangGraph 兼容的类型定义

定义 WorkflowState（LangGraph 的 State）、NodeSpec/EdgeSpec/WorkflowSpec（JSON 工作流定义），
以及 LightweightState 互转桥接。

原则：
- WorkflowState TypedDict → LangGraph 节点读写
- LightweightState dataclass → 持久化 / Checkpoint
- 转换函数在两个表示之间桥接
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Optional, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from operator import add

from langgraph.types import RetryPolicy, CachePolicy

from app.runtime.state_manager.lightweight_state import LightweightState


# ═══════════════════════════════════════════
# LangGraph WorkflowState TypedDict
# ═══════════════════════════════════════════

class WorkflowState(TypedDict, total=False):
    """
    LangGraph 全局 State。

    字段语义与 LightweightState 对齐，但 messages 使用
    Annotated[list, operator.add] 支持 LangGraph 消息累加语义。
    total=False 意味着所有字段可选，graph 入口负责赋初值。
    """

    # ── 任务标识 ──
    task_id: str
    project_id: str

    # ── 流程控制 ──
    current_node: str
    workflow_status: str  # idle | running | paused | waiting_approval | completed | failed
    error_count: int
    max_retries: int

    # ── 引用（核心原则：只存引用，不存内容） ──
    artifact_refs: list[str]
    context_refs: list[str]
    last_checkpoint_id: Optional[str]

    # ── 人工干预 ──
    approval_needed: bool
    approval_result: Optional[bool]

    # ── 最近消息（使用 operator.add 累加 dict 格式消息） ──
    # NOTE: 评估过 add_messages (LangGraph 原生)，但与 dict-based 消息格式不兼容
    # add_messages 会将 dict 转为 LangChain Message 对象，下游代码全部依赖 dict 访问
    messages: Annotated[list, add]
    current_goal: str

    # ── 可观测元数据 ──
    metadata: dict[str, Any]

    # ── 步骤历史（用于看板展示） ──
    steps: list[dict[str, Any]]

    # ── LLM 调用历史 ──
    llm_call_count: int
    total_tokens: int
    total_cost: float


# ═══════════════════════════════════════════
# Default state factory
# ═══════════════════════════════════════════

def create_default_state(
    task_id: str = "",
    project_id: str = "",
    goal: str = "",
) -> WorkflowState:
    """创建带默认值的 WorkflowState"""
    return WorkflowState(
        task_id=task_id,
        project_id=project_id,
        current_node="",
        workflow_status="idle",
        error_count=0,
        max_retries=3,
        artifact_refs=[],
        context_refs=[],
        last_checkpoint_id=None,
        approval_needed=False,
        approval_result=None,
        messages=[],
        current_goal=goal,
        metadata={},
        steps=[],
        llm_call_count=0,
        total_tokens=0,
        total_cost=0.0,
    )


# ═══════════════════════════════════════════
# 桥接函数: WorkflowState ↔ LightweightState
# ═══════════════════════════════════════════

def workflow_state_to_lightweight(state: WorkflowState) -> LightweightState:
    """WorkflowState → LightweightState (for persistence)"""
    return LightweightState(
        task_id=state.get("task_id", ""),
        project_id=state.get("project_id", ""),
        current_node=state.get("current_node", ""),
        workflow_status=state.get("workflow_status", "idle"),
        error_count=state.get("error_count", 0),
        max_retries=state.get("max_retries", 3),
        artifact_refs=list(state.get("artifact_refs", [])),
        context_refs=list(state.get("context_refs", [])),
        checkpoint_id=state.get("last_checkpoint_id"),
        approval_needed=state.get("approval_needed", False),
        approval_result=state.get("approval_result"),
        messages=list(state.get("messages", [])),
        current_goal=state.get("current_goal", ""),
        metadata=dict(state.get("metadata", {})),
        steps=list(state.get("steps", [])),
    )


def lightweight_to_workflow_state(ls: LightweightState) -> WorkflowState:
    """LightweightState → WorkflowState (for graph execution)"""
    return WorkflowState(
        task_id=ls.task_id,
        project_id=ls.project_id,
        current_node=ls.current_node,
        workflow_status=ls.workflow_status,
        error_count=ls.error_count,
        max_retries=ls.max_retries,
        artifact_refs=list(ls.artifact_refs),
        context_refs=list(ls.context_refs),
        last_checkpoint_id=ls.checkpoint_id,
        approval_needed=ls.approval_needed,
        approval_result=ls.approval_result,
        messages=list(ls.messages),
        current_goal=ls.current_goal,
        metadata=dict(ls.metadata),
        steps=list(ls.steps),
        llm_call_count=0,
        total_tokens=0,
        total_cost=0.0,
    )


# ═══════════════════════════════════════════
# 工作流 JSON Spec 类型
# ═══════════════════════════════════════════

class NodeType(str, Enum):
    """工作流节点类型"""
    START = "start"
    END = "end"
    LLM = "llm"
    TOOL = "tool"
    CONDITION = "condition"
    HUMAN_APPROVAL = "human_approval"


class NodeSpec(BaseModel):
    """工作流 JSON 中的节点定义"""
    id: str = Field(..., description="节点唯一 ID")
    type: NodeType = Field(..., description="节点类型")
    label: str = Field(default="", description="节点显示名称")
    config: dict[str, Any] = Field(default_factory=dict, description="节点配置（类型相关）")


class EdgeType(str, Enum):
    """边类型"""
    DIRECT = "direct"           # 直接边：无条件跳转
    CONDITIONAL = "conditional"  # 条件边：根据 state 决定目标
    SEND = "send"               # 并行分发边：对列表每项 fan-out 到同一个节点


class EdgeSpec(BaseModel):
    """工作流 JSON 中的边定义"""
    source: str = Field(..., alias="from", description="源节点 ID")
    target: str = Field(default="", alias="to", description="目标节点 ID（direct/conditional 类型使用；send 类型可省略）")
    condition: Optional[str] = Field(default=None, description="条件表达式（conditional 类型使用）")
    edge_type: EdgeType = Field(default=EdgeType.DIRECT, description="边类型")
    send_node: str = Field(default="", description="send 类型：fan-out 目标节点 ID")
    items_expr: str = Field(default="", description="send 类型：从 state 获取列表的表达式（如 'state.items'）")
    then: Optional[str] = Field(default=None, description="条件满足后强制经过的中间节点")

    model_config = ConfigDict(populate_by_name=True)

    @property
    def effective_type(self) -> EdgeType:
        """推断边的实际类型：优先用 edge_type，否则从 condition 和 send_node 推断"""
        if self.edge_type == EdgeType.SEND or self.send_node:
            return EdgeType.SEND
        if self.condition:
            return EdgeType.CONDITIONAL
        return EdgeType.DIRECT


class NodeDefaults(BaseModel):
    """全局节点默认策略配置。

    对应 LangGraph StateGraph.set_node_defaults() 的参数。
    retry_policy / cache_policy / timeout 语义与 LangGraph 原生类型一致。
    """
    retry_max_attempts: int = Field(default=3, ge=1, description="最大重试次数（含首次）")
    retry_initial_interval: float = Field(default=0.5, gt=0, description="首次重试间隔（秒）")
    retry_backoff_factor: float = Field(default=2.0, gt=0, description="退避乘数")
    retry_max_interval: float = Field(default=128.0, gt=0, description="最大重试间隔（秒）")
    retry_jitter: bool = Field(default=True, description="是否添加随机抖动")
    cache_ttl: Optional[int] = Field(default=None, ge=1, description="缓存 TTL（秒），None 表示永不过期")
    timeout_seconds: Optional[float] = Field(default=None, gt=0, description="节点执行超时（秒）")

    def to_retry_policy(self) -> Optional[RetryPolicy]:
        """转为 LangGraph RetryPolicy"""
        return RetryPolicy(
            initial_interval=self.retry_initial_interval,
            backoff_factor=self.retry_backoff_factor,
            max_interval=self.retry_max_interval,
            max_attempts=self.retry_max_attempts,
            jitter=self.retry_jitter,
        )

    def to_cache_policy(self) -> Optional[CachePolicy]:
        """转为 LangGraph CachePolicy（仅当 cache_ttl 非 None 时启用）"""
        if self.cache_ttl is not None:
            return CachePolicy(ttl=self.cache_ttl)
        return None


class WorkflowSpec(BaseModel):
    """完整的工作流 JSON 定义"""
    name: str = Field(default="untitled", description="工作流名称")
    description: str = Field(default="", description="工作流描述")
    version: str = Field(default="1.0", description="版本号")
    entry_node: str = Field(default="", description="入口节点 ID（不指定则取第一个 start 节点）")
    nodes: list[NodeSpec] = Field(default_factory=list, description="节点列表")
    edges: list[EdgeSpec] = Field(default_factory=list, description="边列表")
    node_defaults: Optional["NodeDefaults"] = Field(default=None, description="全局节点默认策略（重试/缓存/超时）")
    interrupt_before: list[str] = Field(default_factory=list, description="在这些节点前自动中断")
    interrupt_after: list[str] = Field(default_factory=list, description="在这些节点后自动中断")

    def get_entry_node_id(self) -> str:
        """获取入口节点 ID"""
        if self.entry_node:
            return self.entry_node
        # 默认取第一个 start 类型节点
        for node in self.nodes:
            if node.type == NodeType.START:
                return node.id
        # 兜底取第一个节点
        if self.nodes:
            return self.nodes[0].id
        raise ValueError("WorkflowSpec has no nodes")

    def get_outgoing_edges(self, node_id: str) -> list[EdgeSpec]:
        """获取从 node_id 出发的所有边"""
        return [e for e in self.edges if e.source == node_id]

    def get_incoming_edges(self, node_id: str) -> list[EdgeSpec]:
        """获取到达 node_id 的所有边"""
        return [e for e in self.edges if e.target == node_id]


# ═══════════════════════════════════════════
# 示例 Workflow JSON (用于测试和演示)
# ═══════════════════════════════════════════

EXAMPLE_WORKFLOW = WorkflowSpec(
    name="代码审查工作流",
    description="提交 PR → 自动审查 → 人工确认 → 合并",
    nodes=[
        NodeSpec(id="start", type=NodeType.START, label="开始"),
        NodeSpec(
            id="analyze",
            type=NodeType.LLM,
            label="AI 代码分析",
            config={
                "system_prompt": "你是一个代码审查专家。分析以下代码变更并提供审查意见。",
                "model": "gpt-4",
                "temperature": 0.3,
            },
        ),
        NodeSpec(
            id="run_tests",
            type=NodeType.TOOL,
            label="运行测试",
            config={
                "tool_name": "run_tests",
                "args_template": {},
            },
        ),
        NodeSpec(
            id="check_result",
            type=NodeType.CONDITION,
            label="检查测试结果",
            config={
                "expression": "state.get('workflow_status') == 'completed'",
            },
        ),
        NodeSpec(
            id="request_approval",
            type=NodeType.HUMAN_APPROVAL,
            label="请求人工审批",
            config={
                "message": "测试全部通过，是否继续合并？",
                "timeout_seconds": 3600,
            },
        ),
        NodeSpec(id="end", type=NodeType.END, label="结束"),
    ],
    edges=[
        EdgeSpec(source="start", target="analyze"),
        EdgeSpec(source="analyze", target="run_tests"),
        EdgeSpec(source="run_tests", target="check_result"),
        EdgeSpec(source="check_result", target="request_approval", condition="true"),
        EdgeSpec(source="check_result", target="end", condition="false"),
        EdgeSpec(source="request_approval", target="end"),
    ],
)
