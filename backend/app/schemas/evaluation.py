"""
W18 Self Evaluation — API Schema 定义

对应 EvaluationRecord 的入参/出参 schema。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# 维度得分 Schema
# ============================================================================


class DimensionScoreSchema(BaseModel):
    """单个评估维度的得分"""
    metric: str = Field(description="评估维度标识，如 task_success、hallucination")
    score: float = Field(ge=0.0, le=1.0, description="维度得分 0~1")
    weight: float = Field(default=1.0, ge=0.0, description="维度权重")
    passed: bool = Field(default=True, description="是否达到阈值")
    threshold: float = Field(default=0.6, ge=0.0, le=1.0, description="维度阈值")
    reason: str = Field(default="", description="评分理由")
    details: Dict[str, Any] = Field(default_factory=dict, description="详细数据")


# ============================================================================
# 问题 Schema
# ============================================================================


class IssueSchema(BaseModel):
    """评估发现的具体问题"""
    code: str = Field(description="问题代码，如 HALLUCINATION_UNSUPPORTED_CLAIM")
    severity: str = Field(
        default="minor",
        description="严重程度：critical / major / minor / info",
    )
    message: str = Field(description="人类可读描述")
    metric: str = Field(default="", description="所属评估维度")
    suggestion: str = Field(default="", description="改进建议")
    location: str = Field(default="", description="问题位置")
    evidence: str = Field(default="", description="证据引用")
    score_penalty: float = Field(default=0.0, ge=0.0, description="扣分值")


# ============================================================================
# 评估上下文 Schema（请求用）
# ============================================================================


class EvaluationContextSchema(BaseModel):
    """评估执行时需要的上下文数据"""
    task_id: str = Field(description="任务 ID")
    node_id: str = Field(default="")
    agent_name: str = Field(default="")

    # 输入
    goal_description: str = Field(default="", description="任务/节点目标")
    input_data: Dict[str, Any] = Field(default_factory=dict)

    # 输出
    output_data: Dict[str, Any] = Field(default_factory=dict)
    output_text: str = Field(default="", description="原始输出文本")

    # 执行统计
    tokens_used: int = Field(default=0, ge=0, description="消耗 token 总数")
    tokens_input: int = Field(default=0, ge=0, description="输入 token 数")
    tokens_output: int = Field(default=0, ge=0, description="输出 token 数")
    tool_calls_total: int = Field(default=0, ge=0, description="工具调用总数")
    tool_calls_success: int = Field(default=0, ge=0, description="工具调用成功数")
    error_count: int = Field(default=0, ge=0, description="错误次数")
    recovery_count: int = Field(default=0, ge=0, description="恢复次数")
    execution_time_ms: float = Field(default=0.0, ge=0.0, description="执行耗时")
    context_window_used: int = Field(default=0, ge=0, description="上下文窗口使用量")
    context_window_max: int = Field(default=128000, ge=0, description="上下文窗口最大值")

    # 代码评估用
    code_output: str = Field(default="", description="生成的代码文本")
    code_language: str = Field(default="", description="代码语言")

    def to_runtime_context(self):
        """转换为 runtime EvaluationContext"""
        from app.runtime.evaluation.models import EvaluationContext
        return EvaluationContext(
            task_id=self.task_id,
            node_id=self.node_id,
            agent_name=self.agent_name,
            goal_description=self.goal_description,
            input_data=self.input_data,
            output_data=self.output_data,
            output_text=self.output_text,
            tokens_used=self.tokens_used,
            tokens_input=self.tokens_input,
            tokens_output=self.tokens_output,
            tool_calls_total=self.tool_calls_total,
            tool_calls_success=self.tool_calls_success,
            error_count=self.error_count,
            recovery_count=self.recovery_count,
            execution_time_ms=self.execution_time_ms,
            context_window_used=self.context_window_used,
            context_window_max=self.context_window_max,
            code_output=self.code_output,
            code_language=self.code_language,
        )


# ============================================================================
# 评估请求 / 响应 Schema
# ============================================================================


class EvaluationRequest(BaseModel):
    """发起评估请求"""
    task_id: str = Field(description="被评估的任务 ID")
    scope: str = Field(default="task", description="评估范围：task / node / step")
    node_id: str = Field(default="", description="节点 ID（node/step 范围时）")
    agent_name: str = Field(default="", description="Agent 名称")
    context: EvaluationContextSchema = Field(description="评估上下文数据")


class EvaluationResponse(BaseModel):
    """评估结果响应"""
    id: str = Field(description="评估记录 ID")
    task_id: str
    node_id: str = ""
    agent_id: str = ""
    agent_name: str = ""
    scope: str = "task"

    overall_score: float = Field(description="综合得分 0~1")
    passed: bool = Field(description="是否通过")
    threshold: float = Field(default=0.7, description="全局阈值")

    dimension_scores: List[DimensionScoreSchema] = Field(default_factory=list)
    issues: List[IssueSchema] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)

    execution_time_ms: float = Field(default=0.0)
    evaluator_version: str = "1.0"
    evaluation_timestamp: str = ""
    created_at: str = ""
    updated_at: str = ""

    model_config = ConfigDict(from_attributes=True)


class EvaluationSummary(BaseModel):
    """评估摘要（列表用）"""
    task_id: str
    agent_name: str = ""
    overall_score: float = 0.0
    passed: bool = False
    issue_count: int = 0
    critical_count: int = 0
    major_count: int = 0
    evaluation_timestamp: str = ""


class EvaluationStatsResponse(BaseModel):
    """评估统计"""
    total_evaluations: int = 0
    total_tasks_evaluated: int = 0
    average_score: float = 0.0
    pass_rate: float = 0.0
    total_issues_found: int = 0
    critical_issues_count: int = 0
    major_issues_count: int = 0
    top_improvement_areas: List[str] = Field(default_factory=list)
    score_distribution: Dict[str, int] = Field(default_factory=dict)
    dimension_averages: Dict[str, float] = Field(default_factory=dict)


# ============================================================================
# 评估配置 Schema
# ============================================================================


class EvaluatorConfigSchema(BaseModel):
    """评估器配置"""
    global_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="全局通过阈值")
    hallucination_strictness: str = Field(
        default="medium",
        pattern=r"^(low|medium|high)$",
        description="幻觉检测严格程度",
    )
    code_static_analysis: bool = Field(default=False, description="是否启用静态分析")
    disabled_metrics: List[str] = Field(default_factory=list, description="禁用的评估维度")

    class ConfigDict:
        extra = "forbid"


class EvaluationTriggerResponse(BaseModel):
    """触发评估的异步响应"""
    message: str = "Evaluation triggered"
    task_id: str
    status: str = "accepted"
