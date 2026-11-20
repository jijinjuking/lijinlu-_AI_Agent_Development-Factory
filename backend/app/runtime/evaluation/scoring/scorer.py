"""W18 Scoring — 评分计算引擎

支持：
  - 加权平均（各维度自定义权重）
  - 阈值判断（全局 + 局部）
  - 评分归一化（0.0 ~ 1.0）
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from ..models import (
    DimensionScore,
    EvaluationContext,
    EvaluationMetric,
    EvaluationResult,
    EvaluatorConfig,
    Issue,
    Severity,
)

logger = logging.getLogger(__name__)


def compute_weighted_score(
    dimension_scores: List[DimensionScore],
    config: Optional[EvaluatorConfig | float] = None,
) -> tuple[float, bool]:
    """对维度得分做加权平均。

    返回 (score, passed)。
    config 可以是 EvaluatorConfig 或 float（直接用做阈值）。
    如果某个维度未启用（config.enabled_metrics），权重按比例重新分配。
    """
    if isinstance(config, (int, float)):
        threshold = float(config)
        config_obj = None
    elif config is not None:
        threshold = config.global_threshold
        config_obj = config
    else:
        threshold = 0.7
        config_obj = None

    if not dimension_scores:
        return 0.0, False

    total_weight = 0.0
    weighted_sum = 0.0

    for ds in dimension_scores:
        if config_obj and not config_obj.is_enabled(ds.metric):
            continue
        w = ds.weight
        weighted_sum += ds.score * w
        total_weight += w

    if total_weight == 0:
        return 0.0, False
    score = min(1.0, max(0.0, weighted_sum / total_weight))
    passed = score >= threshold
    return score, passed


class Scorer:
    """评分器：整合各维度得分 → 计算综合得分 → 生成建议。"""

    def __init__(self, config: EvaluatorConfig):
        self.config = config

    # ------------------------------------------------------------------
    # 综合评分
    # ------------------------------------------------------------------

    def score(
        self,
        task_id: str,
        dimension_scores: List[DimensionScore],
        node_id: str = "",
        agent_name: str = "",
    ) -> EvaluationResult:
        """计算综合评分结果。

        步骤：
          1. 加权平均各维度得分 → overall_score
          2. 判断 overall_score >= global_threshold → passed
          3. 收集各维度的 issues
          4. 生成改进建议
        """
        overall, passed = compute_weighted_score(dimension_scores, self.config)

        all_issues: List[Issue] = []
        for ds in dimension_scores:
            if "issues" in ds.details:
                all_issues.extend(ds.details["issues"])

        suggestions = self._generate_suggestions(dimension_scores, all_issues)

        return EvaluationResult(
            task_id=task_id,
            node_id=node_id,
            agent_name=agent_name,
            overall_score=overall,
            passed=passed,
            threshold=self.config.global_threshold,
            dimension_scores=dimension_scores,
            issues=all_issues,
            suggestions=suggestions,
        )

    # ------------------------------------------------------------------
    # 统一评估入口（测试期望的 API）
    # ------------------------------------------------------------------

    async def evaluate(self, metric: EvaluationMetric, ctx: EvaluationContext) -> DimensionScore:
        """统一评估入口：根据 metric 类型分发到对应评估方法。"""
        if metric == EvaluationMetric.TASK_SUCCESS:
            return self.evaluate_task_success(ctx)
        elif metric == EvaluationMetric.OUTPUT_RELEVANCE:
            return self.evaluate_output_relevance(ctx)
        elif metric == EvaluationMetric.TOOL_SUCCESS_RATE:
            return self.evaluate_tool_success_rate(ctx)
        elif metric == EvaluationMetric.COST_EFFICIENCY:
            return self.evaluate_cost_efficiency(ctx)
        elif metric == EvaluationMetric.CONTEXT_EFFICIENCY:
            return self.evaluate_context_efficiency(ctx)
        elif metric == EvaluationMetric.RUNTIME_STABILITY:
            return self.evaluate_runtime_stability(ctx)
        elif metric == EvaluationMetric.HALLUCINATION:
            # 幻觉由 HallucinationDetector 负责，这里给满分
            return DimensionScore(
                metric=metric,
                score=1.0,
                weight=self.config.get_weight(metric),                threshold=self.config.get_threshold(metric),
                reason="非幻觉检测维度，默认满分",
                details={},
            )
        elif metric == EvaluationMetric.CODE_QUALITY:
            return DimensionScore(
                metric=metric,
                score=0.8,
                weight=self.config.get_weight(metric),                threshold=self.config.get_threshold(metric),
                reason="代码质量维度（由 CodeQualityChecker 负责）",
                details={},
            )
        else:
            return DimensionScore(
                metric=metric,
                score=0.5,
                weight=self.config.get_weight(metric),                threshold=self.config.get_threshold(metric),
                reason=f"未知评估维度: {metric}",
                details={},
            )

    # ------------------------------------------------------------------
    # 快速评估（rule-based，不需要 LLM）
    # ------------------------------------------------------------------

    def evaluate_task_success(self, ctx: EvaluationContext) -> DimensionScore:
        """任务成功度评分。

        规则：
          - 输出非空 +1.0
          - 包含目标关键词 +0.2（如果有 goal_description）
          - 无错误 +0.3
          - 有恢复成功 +0.1
        基准分 0.4，最高 1.0。
        """
        threshold = self.config.get_threshold(EvaluationMetric.TASK_SUCCESS)
        score = 0.4  # 有输出就有基本分

        issues: List[Issue] = []

        # 检查输出是否为空
        if ctx.output_text or ctx.output_data:
            score += 0.2
        else:
            issues.append(Issue(
                code="TASK_EMPTY_OUTPUT",
                severity=Severity.CRITICAL,
                message="任务输出为空",
                metric=EvaluationMetric.TASK_SUCCESS,
                suggestion="检查 Agent 执行逻辑，确保产生有效输出",
                score_penalty=0.4,
            ))

        # 检查是否包含目标关键词（如果有 goal_description）
        if ctx.goal_description and ctx.output_text:
            keywords = self._extract_keywords(ctx.goal_description)
            matched = sum(1 for kw in keywords if kw.lower() in ctx.output_text.lower())
            if matched > 0:
                score += 0.2 * min(1.0, matched / max(len(keywords), 1))

        # 无错误加分
        if ctx.error_count == 0:
            score += 0.2
        elif ctx.error_count > 0 and ctx.recovery_count > 0:
            score += 0.1
            issues.append(Issue(
                code="TASK_RECOVERED_ERROR",
                severity=Severity.MINOR,
                message=f"任务执行有 {ctx.error_count} 个错误，但全部自动恢复",
                metric=EvaluationMetric.TASK_SUCCESS,
                suggestion="分析错误根因以减少重试",
                score_penalty=0.05,
            ))
        else:
            issues.append(Issue(
                code="TASK_HAS_ERRORS",
                severity=Severity.MAJOR,
                message=f"任务执行有 {ctx.error_count} 个错误",
                metric=EvaluationMetric.TASK_SUCCESS,
                suggestion="查看错误日志定位根因",
                score_penalty=0.2,
            ))

        passed = score >= threshold
        score = min(1.0, max(0.0, score))

        return DimensionScore(
            metric=EvaluationMetric.TASK_SUCCESS,
            score=score,
            weight=self.config.get_weight(EvaluationMetric.TASK_SUCCESS),            threshold=threshold,
            reason=f"任务成功度 {score:.2f}（阈值 {threshold:.2f}）",
            details={"issues": issues},
        )

    def evaluate_output_relevance(self, ctx: EvaluationContext) -> DimensionScore:
        """输出相关性评分。

        规则：
          - 输出格式符合预期 +0.5
          - 输出内容与目标描述匹配 +0.5
        """
        threshold = self.config.get_threshold(EvaluationMetric.OUTPUT_RELEVANCE)
        score = 0.0
        issues: List[Issue] = []

        # 检查输出格式
        if ctx.output_text:
            # 有长度 = 基本分
            if len(ctx.output_text) > 10:
                score += 0.4
            else:
                score += 0.1
                issues.append(Issue(
                    code="OUTPUT_TOO_SHORT",
                    severity=Severity.MINOR,
                    message=f"输出文本过短（{len(ctx.output_text)} 字符）",
                    metric=EvaluationMetric.OUTPUT_RELEVANCE,
                    suggestion="可能需要更详细的输出",
                    score_penalty=0.1,
                ))

        if ctx.output_data:
            score += 0.2

        # 与目标相关性
        if ctx.goal_description and ctx.output_text:
            relevance = self._estimate_relevance(ctx.goal_description, ctx.output_text)
            score += relevance * 0.4

        passed = score >= threshold
        score = min(1.0, max(0.0, score))

        return DimensionScore(
            metric=EvaluationMetric.OUTPUT_RELEVANCE,
            score=score,
            weight=self.config.get_weight(EvaluationMetric.OUTPUT_RELEVANCE),            threshold=threshold,
            reason=f"输出相关性 {score:.2f}（阈值 {threshold:.2f}）",
            details={"issues": issues},
        )

    def evaluate_tool_success_rate(self, ctx: EvaluationContext) -> DimensionScore:
        """工具成功率评分。

        规则：直接使用 ctx.tool_success_rate 映射到 0~1。
        """
        threshold = self.config.get_threshold(EvaluationMetric.TOOL_SUCCESS_RATE)
        rate = ctx.tool_success_rate
        issues: List[Issue] = []

        if ctx.tool_calls_total > 0 and rate < 0.5:
            issues.append(Issue(
                code="TOOL_LOW_SUCCESS_RATE",
                severity=Severity.MAJOR,
                message=f"工具调用成功率仅 {rate:.0%}（{ctx.tool_calls_success}/{ctx.tool_calls_total}）",
                metric=EvaluationMetric.TOOL_SUCCESS_RATE,
                suggestion="检查工具配置和参数传递是否正确",
                score_penalty=max(0, threshold - rate),
            ))

        passed = rate >= threshold

        return DimensionScore(
            metric=EvaluationMetric.TOOL_SUCCESS_RATE,
            score=rate,
            weight=self.config.get_weight(EvaluationMetric.TOOL_SUCCESS_RATE),            threshold=threshold,
            reason=f"工具成功率 {rate:.0%}（{ctx.tool_calls_success}/{ctx.tool_calls_total}）",
            details={"issues": issues, "total": ctx.tool_calls_total, "success": ctx.tool_calls_success},
        )

    def evaluate_cost_efficiency(self, ctx: EvaluationContext) -> DimensionScore:
        """成本效率评分。

        规则：token_output / token_total 作为有效利用率。
        如果没有 token 数据，给满分。
        """
        threshold = self.config.get_threshold(EvaluationMetric.COST_EFFICIENCY)
        issues: List[Issue] = []

        if ctx.tokens_used == 0:
            return DimensionScore(
                metric=EvaluationMetric.COST_EFFICIENCY,
                score=1.0,
                weight=self.config.get_weight(EvaluationMetric.COST_EFFICIENCY),
            threshold=threshold,
            reason="无 token 数据，默认满分",
                details={},
            )

        # 有效输出 token 占比
        efficiency = ctx.tokens_output / max(ctx.tokens_used, 1)
        score = efficiency

        if efficiency < 0.3:
            issues.append(Issue(
                code="COST_LOW_EFFICIENCY",
                severity=Severity.MINOR,
                message=f"有效 token 利用率仅 {efficiency:.0%}（输出 {ctx.tokens_output}/{ctx.tokens_used} 总 token）",
                metric=EvaluationMetric.COST_EFFICIENCY,
                suggestion="优化 prompt 以减少输入 token，提高输出占比",
                score_penalty=0.1,
            ))

        passed = score >= threshold
        score = min(1.0, max(0.0, score))

        return DimensionScore(
            metric=EvaluationMetric.COST_EFFICIENCY,
            score=score,
            weight=self.config.get_weight(EvaluationMetric.COST_EFFICIENCY),            threshold=threshold,
            reason=f"成本效率 {score:.2f}（输出 token 占比 {efficiency:.0%}）",
            details={"issues": issues, "tokens_used": ctx.tokens_used, "tokens_output": ctx.tokens_output},
        )

    def evaluate_context_efficiency(self, ctx: EvaluationContext) -> DimensionScore:
        """上下文效率评分。

        规则：context_used / context_max 取反（越低越好 → 高分）。
        利用率 20%～80% 最佳（给满分），太低浪费，太高可能溢出。
        """
        threshold = self.config.get_threshold(EvaluationMetric.CONTEXT_EFFICIENCY)
        utilization = ctx.context_utilization
        issues: List[Issue] = []

        if ctx.context_window_used == 0:
            return DimensionScore(
                metric=EvaluationMetric.CONTEXT_EFFICIENCY,
                score=1.0,
                weight=self.config.get_weight(EvaluationMetric.CONTEXT_EFFICIENCY),                threshold=threshold,
                reason="无上下文数据，默认满分",
                details={},
            )

        # 最佳区间 [0.2, 0.8] → 1.0
        if 0.2 <= utilization <= 0.8:
            score = 1.0
        elif utilization < 0.2:
            score = 0.6  # 太低浪费
            issues.append(Issue(
                code="CONTEXT_UNDERUSED",
                severity=Severity.INFO,
                message=f"上下文利用率仅 {utilization:.0%}，可能浪费窗口空间",
                metric=EvaluationMetric.CONTEXT_EFFICIENCY,
                suggestion="增加上下文信息或减少窗口大小",
                score_penalty=0.05,
            ))
        elif utilization < 0.95:
            score = 0.8  # 较高但可接受
        else:
            score = 0.4  # 接近溢出
            issues.append(Issue(
                code="CONTEXT_OVERUSED",
                severity=Severity.MAJOR,
                message=f"上下文利用率 {utilization:.0%}，接近溢出风险",
                metric=EvaluationMetric.CONTEXT_EFFICIENCY,
                suggestion="压缩上下文或使用更大的模型窗口",
                score_penalty=0.2,
            ))

        passed = score >= threshold

        return DimensionScore(
            metric=EvaluationMetric.CONTEXT_EFFICIENCY,
            score=score,
            weight=self.config.get_weight(EvaluationMetric.CONTEXT_EFFICIENCY),            threshold=threshold,
            reason=f"上下文利用率 {utilization:.0%}（{ctx.context_window_used}/{ctx.context_window_max}）",
            details={"issues": issues, "used": ctx.context_window_used, "max": ctx.context_window_max},
        )

    def evaluate_runtime_stability(self, ctx: EvaluationContext) -> DimensionScore:
        """运行时稳定性评分。

        规则：
          - 无错误 = 1.0
          - 有错误但全部恢复 = 0.8
          - 有错误未恢复 = 0.3
        """
        threshold = self.config.get_threshold(EvaluationMetric.RUNTIME_STABILITY)
        issues: List[Issue] = []

        if ctx.error_count == 0:
            score = 1.0
        elif ctx.error_count > 0 and ctx.recovery_count >= ctx.error_count:
            score = 0.8
            issues.append(Issue(
                code="STABILITY_RECOVERED",
                severity=Severity.MINOR,
                message=f"有 {ctx.error_count} 个错误但全部自动恢复",
                metric=EvaluationMetric.RUNTIME_STABILITY,
                suggestion="分析错误模式以预防",
                score_penalty=0.05,
            ))
        else:
            score = 0.3
            unrecovered = ctx.error_count - ctx.recovery_count
            issues.append(Issue(
                code="STABILITY_UNRECOVERED",
                severity=Severity.MAJOR,
                message=f"有 {unrecovered} 个错误未恢复",
                metric=EvaluationMetric.RUNTIME_STABILITY,
                suggestion="检查错误处理逻辑和自动恢复策略",
                score_penalty=0.4,
            ))

        passed = score >= threshold

        return DimensionScore(
            metric=EvaluationMetric.RUNTIME_STABILITY,
            score=score,
            weight=self.config.get_weight(EvaluationMetric.RUNTIME_STABILITY),            threshold=threshold,
            reason=f"运行时稳定性 {score:.1f}（{ctx.error_count} 错误 / {ctx.recovery_count} 恢复）",
            details={"issues": issues, "errors": ctx.error_count, "recoveries": ctx.recovery_count},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_keywords(text: str, max_keywords: int = 5) -> List[str]:
        """从文本中提取关键词（简单基于空格/标点分词）。"""
        import re
        words = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]{2,}', text.lower())
        # 过滤停用词
        stopwords = {"the", "a", "an", "is", "are", "of", "to", "in", "for", "and", "or", "it", "this", "that"}
        keywords = [w for w in words if w not in stopwords]
        return keywords[:max_keywords]

    @staticmethod
    def _estimate_relevance(goal: str, output: str) -> float:
        """估算目标与输出的相关性（基于关键词重叠）。"""
        goal_kw = set(Scorer._extract_keywords(goal, max_keywords=10))
        output_words = set(output.lower().split())
        if not goal_kw:
            return 0.5
        overlap = len(goal_kw & output_words)
        return min(1.0, overlap / len(goal_kw))

    @staticmethod
    def _generate_suggestions(
        dimension_scores: List[DimensionScore],
        all_issues: List[Issue],
    ) -> List[str]:
        """从维度得分和 issues 中提取改进建议。"""
        suggestions: List[str] = []

        # 从 issues 中提取建议
        for issue in all_issues:
            if issue.suggestion and issue.suggestion not in suggestions:
                suggestions.append(f"[{issue.code}] {issue.suggestion}")

        # 从低分维度生成建议
        for ds in dimension_scores:
            if ds.score < 0.5 and ds.metric == EvaluationMetric.CODE_QUALITY:
                if "检查代码是否符合规范" not in " ".join(suggestions):
                    suggestions.append("代码质量评分较低，建议进行代码审查")
            elif ds.score < 0.5 and ds.metric == EvaluationMetric.HALLUCINATION:
                if "幻觉" not in " ".join(suggestions):
                    suggestions.append("检测到可能的幻觉内容，建议人工审核输出")

        return suggestions
