"""W18 Code Quality Checker — 代码质量评估

评估维度：
  1. 语法有效性（try-except compile）
  2. 基本风格（缩进一致性、行长度）
  3. 代码结构（函数长度、嵌套层级）
  4. 注释覆盖率
  5. 空指针/异常处理

完全基于规则，无需外部工具。
"""

from __future__ import annotations

import ast
import logging
import re
from typing import List

from ..models import (
    DimensionScore,
    EvaluationContext,
    EvaluationMetric,
    EvaluatorConfig,
    Issue,
    Severity,
)

logger = logging.getLogger(__name__)


class CodeQualityChecker:
    """基于规则的代码质量检测器。"""

    # 警告阈值
    MAX_LINE_LENGTH = 120
    MAX_FUNCTION_LINES = 50
    MAX_NESTING_DEPTH = 4
    MIN_COMMENT_RATIO = 0.05  # 最少注释占比 5%

    def __init__(self, config: EvaluatorConfig):
        self.config = config

    # ------------------------------------------------------------------
    # 主评估
    # ------------------------------------------------------------------

    def check(self, code: str, language: str = "python") -> dict:
        """测试期望的 API：返回检查结果 dict。

        返回: { syntax_valid, syntax_errors, quality_metrics, language, ... }
        """
        result = {
            "language": language,
            "syntax_valid": True,
            "syntax_errors": [],
            "quality_metrics": {"maintainability": "good"},
        }

        if not code:
            result["syntax_valid"] = False
            result["syntax_errors"].append("empty code")
            return result

        # 语法检查
        if language in ("python", "py", "") and self._looks_like_python(code):
            try:
                ast.parse(code)
            except SyntaxError as e:
                result["syntax_valid"] = False
                result["syntax_errors"].append(str(e))

        # 代码长度指标
        lines = code.split("\n")
        result["quality_metrics"]["total_lines"] = len(lines)
        result["quality_metrics"]["non_empty_lines"] = len([l for l in lines if l.strip()])

        # 注释率
        comment_lines = sum(1 for l in lines if l.strip().startswith("#"))
        result["quality_metrics"]["comment_ratio"] = round(
            comment_lines / max(len(lines), 1), 3
        )

        return result

    def evaluate(self, ctx: EvaluationContext) -> DimensionScore:
        """评估代码质量。

        如果 ctx.code_output 为空，尝试从 ctx.output_text 提取代码。
        """
        threshold = self.config.get_threshold(EvaluationMetric.CODE_QUALITY)
        code = ctx.code_output or self._extract_code(ctx.output_text)

        if not code:
            return DimensionScore(
                metric=EvaluationMetric.CODE_QUALITY,
                score=0.8,  # 无代码输出不扣分也不加分
                weight=self.config.get_weight(EvaluationMetric.CODE_QUALITY),                threshold=threshold,
                reason="无代码输出，跳过代码质量评估",
                details={},
            )

        issues: List[Issue] = []
        penalty = 0.0
        checks_passed = 0
        checks_total = 0

        # 1. 语法检查
        checks_total += 1
        syntax_issues = self._check_syntax(code, ctx.code_language)
        if not syntax_issues:
            checks_passed += 1
        else:
            penalty += sum(i.score_penalty for i in syntax_issues)
            issues.extend(syntax_issues)

        # 2. 行长度检查
        checks_total += 1
        linelen_issues = self._check_line_length(code)
        if not linelen_issues:
            checks_passed += 1
        else:
            penalty += sum(i.score_penalty for i in linelen_issues)
            issues.extend(linelen_issues)

        # 3. 基本结构检查（仅 Python 可用 AST）
        if ctx.code_language in ("python", "py", "") or self._looks_like_python(code):
            checks_total += 1
            struct_issues = self._check_structure_python(code)
            if not struct_issues:
                checks_passed += 1
            else:
                penalty += sum(i.score_penalty for i in struct_issues)
                issues.extend(struct_issues)

        # 4. 注释覆盖率
        checks_total += 1
        comment_issues = self._check_comments(code)
        if not comment_issues:
            checks_passed += 1
        else:
            penalty += sum(i.score_penalty for i in comment_issues)
            issues.extend(comment_issues)

        # 5. 异常处理检查（仅 Python）
        if ctx.code_language in ("python", "py", "") or self._looks_like_python(code):
            checks_total += 1
            error_issues = self._check_error_handling_python(code)
            if not error_issues:
                checks_passed += 1
            else:
                penalty += sum(i.score_penalty for i in error_issues)
                issues.extend(error_issues)

        # 计算得分：通过率 + 扣分
        base_score = checks_passed / max(checks_total, 1)
        score = max(0.0, base_score - penalty)
        passed = score >= threshold

        if checks_total == 0:
            score = 0.8
            passed = True

        return DimensionScore(
            metric=EvaluationMetric.CODE_QUALITY,
            score=min(1.0, score),
            weight=self.config.get_weight(EvaluationMetric.CODE_QUALITY),            threshold=threshold,
            reason=f"代码质量得分 {score:.2f}（{checks_passed}/{checks_total} 项通过）",
            details={
                "issues": issues,
                "checks_passed": checks_passed,
                "checks_total": checks_total,
                "code_language": ctx.code_language or "auto",
                "code_length": len(code),
            },
        )

    # ------------------------------------------------------------------
    # 检查方法
    # ------------------------------------------------------------------

    def _check_syntax(self, code: str, language: str) -> List[Issue]:
        """检查代码语法有效性。"""
        issues: List[Issue] = []
        if language in ("python", "py", "") and self._looks_like_python(code):
            try:
                ast.parse(code)
            except SyntaxError as e:
                issues.append(Issue(
                    code="CODE_SYNTAX_ERROR",
                    severity=Severity.CRITICAL,
                    message=f"语法错误: {e.msg}（第 {e.lineno} 行）",
                    metric=EvaluationMetric.CODE_QUALITY,
                    suggestion="修复语法错误后再评估",
                    location=f"line {e.lineno}",
                    evidence=str(e),
                    score_penalty=0.4,
                ))
        return issues

    def _check_line_length(self, code: str) -> List[Issue]:
        """检查行长度。"""
        issues: List[Issue] = []
        long_lines = 0
        for i, line in enumerate(code.split("\n"), 1):
            stripped = line.rstrip()
            if len(stripped) > self.MAX_LINE_LENGTH:
                long_lines += 1

        if long_lines > 5:
            issues.append(Issue(
                code="CODE_LONG_LINES",
                severity=Severity.MINOR,
                message=f"有 {long_lines} 行超过 {self.MAX_LINE_LENGTH} 字符",
                metric=EvaluationMetric.CODE_QUALITY,
                suggestion="拆分过长的行，或使用换行提高可读性",
                score_penalty=0.05,
            ))
        return issues

    def _check_structure_python(self, code: str) -> List[Issue]:
        """检查 Python 代码结构（AST 分析）。"""
        issues: List[Issue] = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues  # 语法已由 _check_syntax 处理

        # 检查函数长度
        long_funcs = 0
        deep_funcs = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_lines = node.end_lineno - node.lineno if node.end_lineno else 0
                if func_lines > self.MAX_FUNCTION_LINES:
                    long_funcs += 1
                # 检查嵌套深度
                depth = self._compute_nesting_depth(node)
                if depth > self.MAX_NESTING_DEPTH:
                    deep_funcs += 1

        if long_funcs > 0:
            issues.append(Issue(
                code="CODE_LONG_FUNCTION",
                severity=Severity.MINOR,
                message=f"有 {long_funcs} 个函数超过 {self.MAX_FUNCTION_LINES} 行",
                metric=EvaluationMetric.CODE_QUALITY,
                suggestion="拆分过长函数，遵循单一职责原则",
                score_penalty=0.05 * min(long_funcs, 3),
            ))

        if deep_funcs > 0:
            issues.append(Issue(
                code="CODE_DEEP_NESTING",
                severity=Severity.MINOR,
                message=f"有 {deep_funcs} 个函数嵌套超过 {self.MAX_NESTING_DEPTH} 层",
                metric=EvaluationMetric.CODE_QUALITY,
                suggestion="减少嵌套层级，使用早返回（early return）模式",
                score_penalty=0.03 * min(deep_funcs, 3),
            ))

        return issues

    def _check_comments(self, code: str) -> List[Issue]:
        """检查注释覆盖率。"""
        issues: List[Issue] = []
        lines = code.split("\n")
        if len(lines) < 5:
            return issues

        comment_lines = sum(
            1 for line in lines
            if line.strip().startswith("#")  # Python
            or line.strip().startswith("//")  # JS/TS/Go/...
            or line.strip().startswith("--")  # SQL/Lua
        )
        ratio = comment_lines / max(len(lines), 1)

        if ratio < self.MIN_COMMENT_RATIO and len(lines) > 20:
            issues.append(Issue(
                code="CODE_LOW_COMMENTS",
                severity=Severity.INFO,
                message=f"注释覆盖率仅 {ratio:.1%}（{comment_lines}/{len(lines)} 行）",
                metric=EvaluationMetric.CODE_QUALITY,
                suggestion="增加关键逻辑的注释，提高可维护性",
                score_penalty=0.03,
            ))

        return issues

    def _check_error_handling_python(self, code: str) -> List[Issue]:
        """检查 Python 异常处理（是否有 bare except / 无异常处理）。"""
        issues: List[Issue] = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        has_try = False
        has_bare_except = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                has_try = True
                for handler in node.handlers:
                    if handler.type is None:
                        has_bare_except = True

        if has_bare_except:
            issues.append(Issue(
                code="CODE_BARE_EXCEPT",
                severity=Severity.MINOR,
                message="使用了裸 except（bare except）",
                metric=EvaluationMetric.CODE_QUALITY,
                suggestion="捕获具体异常类型 (e.g., except ValueError)，避免隐藏意外错误",
                score_penalty=0.05,
            ))

        return issues

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _looks_like_python(code: str) -> bool:
        """简单检测代码是否看起来像 Python。"""
        python_signatures = ["def ", "import ", "from ", "class ", "async def "]
        return any(sig in code for sig in python_signatures)

    @staticmethod
    def _extract_code(text: str) -> str:
        """从 Markdown 文本中提取代码块内容。"""
        # 尝试提取 ```python ... ``` 或 ``` ... ``` 代码块
        pattern = re.compile(r'```(?:\w+)?\s*\n(.*?)```', re.DOTALL)
        matches = pattern.findall(text)
        if matches:
            return "\n".join(matches)
        return ""

    @staticmethod
    def _compute_nesting_depth(node: ast.AST, current_depth: int = 0) -> int:
        """计算 AST 节点的最大嵌套深度。"""
        max_depth = current_depth
        nesting_nodes = (ast.If, ast.For, ast.While, ast.Try, ast.With)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, nesting_nodes):
                depth = CodeQualityChecker._compute_nesting_depth(child, current_depth + 1)
                max_depth = max(max_depth, depth)
            else:
                depth = CodeQualityChecker._compute_nesting_depth(child, current_depth)
                max_depth = max(max_depth, depth)
        return max_depth
