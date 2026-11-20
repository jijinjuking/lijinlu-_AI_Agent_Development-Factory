"""W18 Self Evaluation — 数据模型

评估维度：
  - task_success:      任务目标是否达成
  - tool_success_rate: 工具调用成功率
  - hallucination:     幻觉/虚构信息检测
  - cost_efficiency:   成本效率（token / output 比值）
  - context_efficiency: 上下文窗口利用率
  - runtime_stability:  运行时稳定性（错误率/恢复率）
  - code_quality:      代码质量
  - output_relevance:  输出与目标的相关性
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================================
# Enums
# ============================================================================


def _serialize_details(obj: Any) -> Any:
    """递归将 details 字典中的 dataclass 对象（Issue/DimensionScore 等）转为 dict。

    防止 JSON 序列化时报 "Object of type X is not JSON serializable"。
    """
    if isinstance(obj, dict):
        return {k: _serialize_details(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_details(item) for item in obj]
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    # Enum → 取 .value
    if hasattr(obj, "value") and isinstance(obj, Enum):
        return obj.value
    return obj


class EvaluationMetric(str, Enum):
    """评估维度枚举"""
    TASK_SUCCESS = "task_success"
    TOOL_SUCCESS_RATE = "tool_success_rate"
    HALLUCINATION = "hallucination"
    COST_EFFICIENCY = "cost_efficiency"
    CONTEXT_EFFICIENCY = "context_efficiency"
    RUNTIME_STABILITY = "runtime_stability"
    CODE_QUALITY = "code_quality"
    OUTPUT_RELEVANCE = "output_relevance"


class EvaluationScope(str, Enum):
    """评估范围"""
    STEP = "step"        # 单步评估
    NODE = "node"        # 节点级评估
    TASK = "task"        # 任务级综合评估


class Severity(str, Enum):
    """问题严重程度"""
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


# ============================================================================
# Dimension Score
# ============================================================================


@dataclass
class DimensionScore:
    """单个评估维度的得分"""
    metric: EvaluationMetric
    score: float                      # 0.0 ~ 1.0，越高越好
    weight: float = 1.0               # 该维度的权重（加权平均用）
    threshold: float = 0.6            # 该维度的本地阈值
    reason: str = ""                  # 评分理由
    details: Dict[str, Any] = field(default_factory=dict)  # 详细数据
    _passed: bool = field(default=True, repr=False)  # 内部字段，由 __post_init__ 计算

    def __post_init__(self):
        if self._passed is True and not hasattr(self, '_passed_set'):
            # 自动计算 passed
            self.passed = self.score >= self.threshold

    @property
    def passed(self) -> bool:
        return self.score >= self.threshold

    @passed.setter
    def passed(self, value: bool):
        self._passed = value

    def to_dict(self) -> dict:
        return {
            "metric": self.metric.value,
            "score": round(self.score, 4),
            "weight": self.weight,
            "passed": self.passed,
            "threshold": self.threshold,
            "reason": self.reason,
            "details": _serialize_details(self.details),
        }


# ============================================================================
# Issue（评估发现的问题）
# ============================================================================


@dataclass
class Issue:
    """评估发现的具体问题"""
    code: str                        # 问题代码，如 "HALLUCINATION_UNSUPPORTED_CLAIM"
    severity: Severity
    message: str                     # 人类可读描述
    metric: EvaluationMetric
    suggestion: str = ""             # 改进建议
    location: str = ""               # 问题位置（如 node_id / tool_name）
    evidence: str = ""               # 证据（引用原文）
    score_penalty: float = 0.0       # 该问题导致的扣分

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "metric": self.metric.value,
            "suggestion": self.suggestion,
            "location": self.location,
            "evidence": self.evidence,
            "score_penalty": self.score_penalty,
        }


# ============================================================================
# Evaluation Result
# ============================================================================


@dataclass
class EvaluationResult:
    """一次评估的完整结果"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    scope: EvaluationScope = EvaluationScope.TASK
    node_id: str = ""                 # 被评估的节点（step/node 范围时）
    agent_name: str = ""

    # 综合得分
    overall_score: float = 0.0       # 0.0 ~ 1.0
    passed: bool = False             # overall_score >= global_threshold
    threshold: float = 0.7           # 全局阈值

    # 维度得分
    dimension_scores: List[DimensionScore] = field(default_factory=list)

    # 发现的问题
    issues: List[Issue] = field(default_factory=list)

    # 改进建议
    suggestions: List[str] = field(default_factory=list)

    # 元数据
    execution_time_ms: float = 0.0   # 评估耗时（毫秒）
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "scope": self.scope.value,
            "node_id": self.node_id,
            "agent_name": self.agent_name,
            "overall_score": round(self.overall_score, 4),
            "passed": self.passed,
            "threshold": self.threshold,
            "dimension_scores": [ds.to_dict() for ds in self.dimension_scores],
            "issues": [i.to_dict() for i in self.issues],
            "suggestions": self.suggestions,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "timestamp": self.timestamp,
        }

    @property
    def critical_issues(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == Severity.CRITICAL]

    @property
    def major_issues(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == Severity.MAJOR]

    def get_metric(self, metric: EvaluationMetric) -> Optional[DimensionScore]:
        for ds in self.dimension_scores:
            if ds.metric == metric:
                return ds
        return None


# ============================================================================
# Evaluation Context（传给评估器的上下文）
# ============================================================================


@dataclass
class EvaluationContext:
    """评估执行时需要的上下文数据"""
    task_id: str
    node_id: str = ""
    agent_name: str = ""

    # 输入
    goal_description: str = ""          # 任务/节点目标
    input_data: Dict[str, Any] = field(default_factory=dict)

    # 输出
    output_data: Dict[str, Any] = field(default_factory=dict)
    output_text: str = ""               # LLM 生成的原始文本（用于幻觉检测）

    # 执行统计
    tokens_used: int = 0                # 消耗 token 数（含输入 + 输出）
    tokens_input: int = 0
    tokens_output: int = 0
    tool_calls_total: int = 0           # 工具调用总数
    tool_calls_success: int = 0         # 工具调用成功数
    error_count: int = 0                # 错误次数
    recovery_count: int = 0             # 恢复次数
    execution_time_ms: float = 0.0      # 执行耗时
    context_window_used: int = 0        # 上下文窗口使用量
    context_window_max: int = 128000    # 上下文窗口最大值

    # 代码相关（code_quality 评估用）
    code_output: str = ""               # 生成的代码文本
    code_language: str = ""

    @property
    def tool_success_rate(self) -> float:
        if self.tool_calls_total == 0:
            return 1.0
        return self.tool_calls_success / self.tool_calls_total

    @property
    def context_utilization(self) -> float:
        if self.context_window_max == 0:
            return 0.0
        return self.context_window_used / self.context_window_max

    @property
    def cost_per_output_token(self) -> float:
        if self.tokens_output == 0:
            return 0.0
        return self.tokens_used / self.tokens_output

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "node_id": self.node_id,
            "agent_name": self.agent_name,
            "goal_description": self.goal_description,
            "tokens_used": self.tokens_used,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "tool_calls_total": self.tool_calls_total,
            "tool_calls_success": self.tool_calls_success,
            "tool_success_rate": round(self.tool_success_rate, 4),
            "error_count": self.error_count,
            "recovery_count": self.recovery_count,
            "execution_time_ms": self.execution_time_ms,
            "context_utilization": round(self.context_utilization, 4),
            "cost_per_output_token": round(self.cost_per_output_token, 2),
        }


# ============================================================================
# Evaluator Config
# ============================================================================


@dataclass
class EvaluatorConfig:
    """评估器全局配置"""
    # 默认阈值
    global_threshold: float = 0.7

    # 各维度权重和本地阈值
    weights: Dict[EvaluationMetric, float] = field(default_factory=lambda: {
        EvaluationMetric.TASK_SUCCESS: 0.25,
        EvaluationMetric.OUTPUT_RELEVANCE: 0.15,
        EvaluationMetric.TOOL_SUCCESS_RATE: 0.15,
        EvaluationMetric.CODE_QUALITY: 0.10,
        EvaluationMetric.HALLUCINATION: 0.10,
        EvaluationMetric.COST_EFFICIENCY: 0.10,
        EvaluationMetric.CONTEXT_EFFICIENCY: 0.05,
        EvaluationMetric.RUNTIME_STABILITY: 0.10,
    })

    thresholds: Dict[EvaluationMetric, float] = field(default_factory=lambda: {
        EvaluationMetric.TASK_SUCCESS: 0.6,
        EvaluationMetric.OUTPUT_RELEVANCE: 0.5,
        EvaluationMetric.TOOL_SUCCESS_RATE: 0.7,
        EvaluationMetric.CODE_QUALITY: 0.6,
        EvaluationMetric.HALLUCINATION: 0.5,
        EvaluationMetric.COST_EFFICIENCY: 0.4,
        EvaluationMetric.CONTEXT_EFFICIENCY: 0.3,
        EvaluationMetric.RUNTIME_STABILITY: 0.6,
    })

    # 启用的评分器
    enabled_metrics: List[EvaluationMetric] = field(default_factory=lambda: list(EvaluationMetric))

    # Hallucination 检测强度：low / medium / high
    hallucination_strictness: str = "medium"

    # Code quality: 是否执行静态分析
    code_static_analysis: bool = False

    def get_weight(self, metric: EvaluationMetric) -> float:
        return self.weights.get(metric, 0.0)

    def get_threshold(self, metric: EvaluationMetric) -> float:
        return self.thresholds.get(metric, 0.6)

    def is_enabled(self, metric: EvaluationMetric) -> bool:
        return metric in self.enabled_metrics
