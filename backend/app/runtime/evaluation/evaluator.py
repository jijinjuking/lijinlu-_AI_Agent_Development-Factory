"""W18 Self Evaluation — 主评估器

整合所有维度的评估：
  - task_success       (scoring)
  - output_relevance   (scoring)
  - tool_success_rate  (scoring / tool_metrics)
  - cost_efficiency    (scoring)
  - context_efficiency (scoring)
  - runtime_stability  (scoring)
  - hallucination      (hallucination/)
  - code_quality      (code_quality/)

工作流程：
  1. 接收 EvaluationContext（由 Kernel 在执行后填充）
  2. 调用各维度评分器 → List[DimensionScore]
  3. 调用 Scorer.score() → EvaluationResult
  4. 发布 evaluation_completed 事件
  5. 返回 EvaluationResult
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

from .code_quality import CodeQualityChecker
from .hallucination import HallucinationDetector
from .models import (
    EvaluationContext,
    EvaluationMetric,
    EvaluationResult,
    EvaluationScope,
    EvaluatorConfig,
)
from .scoring import Scorer
from .tool_metrics import ToolMetricsCollector

logger = logging.getLogger(__name__)


class SelfEvaluator:
    """W18 主评估器。

    用法：
        ctx = EvaluationContext(task_id=..., output_text=..., ...)
        evaluator = SelfEvaluator(config)
        result = await evaluator.evaluate(task_id, ctx, scope=EvaluationScope.TASK)
    """

    def __init__(
        self,
        config: Optional[EvaluatorConfig] = None,
        tool_metrics: Optional[ToolMetricsCollector] = None,
    ):
        self.config = config or EvaluatorConfig()
        self.scorer = Scorer(self.config)
        self.hallucination_detector = HallucinationDetector(self.config)
        self.code_checker = CodeQualityChecker(self.config)
        self.tool_metrics = tool_metrics or ToolMetricsCollector()

    # ------------------------------------------------------------------
    # 主评估入口
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        task_id: str,
        ctx: EvaluationContext,
        scope: EvaluationScope = EvaluationScope.TASK,
        node_id: str = "",
        agent_name: str = "",
    ) -> EvaluationResult:
        """对给定上下文执行完整评估。

        返回 EvaluationResult（含综合得分 + 各维度得分 + issues + 建议）。
        """
        start_ms = time.time() * 1000.0
        dimension_scores: List[DimensionScore] = []

        # 1. Task Success
        if self.config.is_enabled(EvaluationMetric.TASK_SUCCESS):
            ds = self.scorer.evaluate_task_success(ctx)
            dimension_scores.append(ds)
            logger.debug("TaskSuccess score=%.2f for task=%s", ds.score, task_id)

        # 2. Output Relevance
        if self.config.is_enabled(EvaluationMetric.OUTPUT_RELEVANCE):
            ds = self.scorer.evaluate_output_relevance(ctx)
            dimension_scores.append(ds)

        # 3. Tool Success Rate
        if self.config.is_enabled(EvaluationMetric.TOOL_SUCCESS_RATE):
            ds = self.scorer.evaluate_tool_success_rate(ctx)
            dimension_scores.append(ds)

        # 4. Cost Efficiency
        if self.config.is_enabled(EvaluationMetric.COST_EFFICIENCY):
            ds = self.scorer.evaluate_cost_efficiency(ctx)
            dimension_scores.append(ds)

        # 5. Context Efficiency
        if self.config.is_enabled(EvaluationMetric.CONTEXT_EFFICIENCY):
            ds = self.scorer.evaluate_context_efficiency(ctx)
            dimension_scores.append(ds)

        # 6. Runtime Stability
        if self.config.is_enabled(EvaluationMetric.RUNTIME_STABILITY):
            ds = self.scorer.evaluate_runtime_stability(ctx)
            dimension_scores.append(ds)

        # 7. Hallucination
        if self.config.is_enabled(EvaluationMetric.HALLUCINATION):
            ds = self.hallucination_detector.evaluate(ctx)
            dimension_scores.append(ds)

        # 8. Code Quality
        if self.config.is_enabled(EvaluationMetric.CODE_QUALITY):
            ds = self.code_checker.evaluate(ctx)
            dimension_scores.append(ds)

        # 计算综合得分
        result = self.scorer.score(
            task_id=task_id,
            dimension_scores=dimension_scores,
            node_id=node_id,
            agent_name=agent_name,
        )
        result.scope = scope
        result.execution_time_ms = (time.time() * 1000.0) - start_ms

        level = "WARN" if not result.passed else "INFO"
        logger.log(
            getattr(logging, level),
            "Evaluation %s: overall=%.2f passed=%s issues=%d task=%s",
            scope.value,
            result.overall_score,
            result.passed,
            len(result.issues),
            task_id,
        )

        return result

    async def evaluate_node(
        self,
        task_id: str,
        node_id: str,
        ctx: EvaluationContext,
        agent_name: str = "",
    ) -> EvaluationResult:
        """评估单个节点（step 级别）。"""
        return await self.evaluate(
            task_id=task_id,
            ctx=ctx,
            scope=EvaluationScope.NODE,
            node_id=node_id,
            agent_name=agent_name,
        )

    async def evaluate_step(
        self,
        task_id: str,
        node_id: str,
        ctx: EvaluationContext,
        agent_name: str = "",
    ) -> EvaluationResult:
        """评估单步（step 级别，比 node 更细）。"""
        return await self.evaluate(
            task_id=task_id,
            ctx=ctx,
            scope=EvaluationScope.STEP,
            node_id=node_id,
            agent_name=agent_name,
        )

    # ------------------------------------------------------------------
    # 快速评估（仅用 rule-based，不调用 LLM）
    # ------------------------------------------------------------------

    def evaluate_quick(self, task_id: str, ctx: EvaluationContext) -> EvaluationResult:
        """同步快速评估（不调用 LLM，仅 rule-based）。"""
        start_ms = time.time() * 1000.0
        dimension_scores: List[DimensionScore] = []

        if self.config.is_enabled(EvaluationMetric.TASK_SUCCESS):
            dimension_scores.append(self.scorer.evaluate_task_success(ctx))
        if self.config.is_enabled(EvaluationMetric.HALLUCINATION):
            dimension_scores.append(self.hallucination_detector.evaluate(ctx))
        if self.config.is_enabled(EvaluationMetric.CODE_QUALITY):
            dimension_scores.append(self.code_checker.evaluate(ctx))

        result = self.scorer.score(task_id, dimension_scores)
        result.execution_time_ms = (time.time() * 1000.0) - start_ms
        return result

    # ------------------------------------------------------------------
    # Tool Metrics 代理方法
    # ------------------------------------------------------------------

    def record_tool_call(self, record: "ToolCallRecord") -> None:
        """记录一次工具调用（供 ToolRuntime 回调）。"""
        self.tool_metrics.record(record)

    def get_tool_metrics(self, tool_name: str):
        return self.tool_metrics.get_metrics(tool_name)

    def get_tool_summary(self):
        return self.tool_metrics.get_summary()
