"""W18 Hallucination Detection — 基于规则的幻觉检测

检测策略（无需 LLM）：
  1. 虚构文件路径检测（如 /fake/path/to/file.py）
  2. 自相矛盾检测（前后不一致的声明）
  3. 离谱数字检测（如 "1000000%" 成功率）
  4. 不存在 API / 方法名检测（如 fake_library.non_existent_method）
  5. 过度自信检测（"绝对正确"、"100%无误"）

strictness levels:
  - low:    只检测明显的幻觉（虚构路径、离谱数字）
  - medium: 检测低+中（自相矛盾、过度自信）
  - high:   检测全部（含可疑 API 方法名）
"""

from __future__ import annotations

import re
import logging
from typing import List, Tuple

from ..models import (
    DimensionScore,
    EvaluationContext,
    EvaluationMetric,
    EvaluatorConfig,
    Issue,
    Severity,
)

logger = logging.getLogger(__name__)

# 常见编程语言的合法扩展名
KNOWN_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".c", ".cpp",
    ".h", ".hpp", ".rb", ".php", ".swift", ".kt", ".scala", ".cs", ".vue",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".html", ".css", ".scss",
    ".md", ".txt", ".sh", ".bat", ".ps1", ".sql", ".graphql",
}

# 明显的虚构路径模式
FAKE_PATH_PATTERNS = [
    # /fake/..., /dummy/..., /tmp/test/...（过于通用的 test 路径）
    re.compile(r"/fake/[\w/.-]+", re.IGNORECASE),
    re.compile(r"/dummy/[\w/.-]+", re.IGNORECASE),
    re.compile(r"/test_data/[\w/.-]+", re.IGNORECASE),
    re.compile(r"/mock/[\w/.-]+", re.IGNORECASE),
    # 明显的占位路径
    re.compile(r"/path/to/[\w/.-]+", re.IGNORECASE),
    re.compile(r"/your/path/[\w/.-]+", re.IGNORECASE),
    re.compile(r"/example/[\w/.-]+", re.IGNORECASE),
    re.compile(r"/replace/with/[\w/.-]+", re.IGNORECASE),
]

# 过度自信短语
OVERCONFIDENCE_PATTERNS = [
    re.compile(r"绝对正确", re.IGNORECASE),
    re.compile(r"100%无误", re.IGNORECASE),
    re.compile(r"绝对没有(问题|错误|bug)", re.IGNORECASE),
    re.compile(r"完美无[瑕疵缺]", re.IGNORECASE),
    re.compile(r"绝对可靠", re.IGNORECASE),
    re.compile(r"永远不[会出]", re.IGNORECASE),
]

# 离谱数字（百分比 > 100% 或无意义的大数字）
ABSURD_NUMBER_PATTERNS = [
    re.compile(r"\d{3,}\s*%\s*(成功率|准确率|正确率|完成率)"),
    re.compile(r"(成功率|准确率|正确率)[:：]?\s*\d{3,}\s*%"),
]

# 常见的虚构 API/方法名前缀
FAKE_API_PATTERNS = [
    re.compile(r'\b(fake|dummy|mock|stub|test)_(library|api|module|function|class|method)s?\b', re.IGNORECASE),
    re.compile(r'\bnon_existent_\w+\b', re.IGNORECASE),
]


class HallucinationDetector:
    """基于规则的幻觉检测器。"""

    def __init__(self, config: EvaluatorConfig):
        self.config = config
        self.strictness = config.hallucination_strictness

    # ------------------------------------------------------------------
    # 主评估入口
    # ------------------------------------------------------------------

    def evaluate(self, ctx: EvaluationContext) -> DimensionScore:
        """评估输出的幻觉程度。委托给 detect_text()。"""
        if not ctx.output_text:
            return DimensionScore(
                metric=EvaluationMetric.HALLUCINATION,
                score=1.0,
                weight=self.config.get_weight(EvaluationMetric.HALLUCINATION),                threshold=self.config.get_threshold(EvaluationMetric.HALLUCINATION),
                reason="无文本输出，跳过幻觉检测",
                details={},
            )
        issues = self.detect_text(ctx.output_text, ctx.goal_description, ctx.output_data or {})
        penalty = sum(i.score_penalty for i in issues)
        score = max(0.0, 1.0 - penalty)
        threshold = self.config.get_threshold(EvaluationMetric.HALLUCINATION)
        passed = score >= threshold
        reason = "无幻觉迹象" if not issues else f"检测到 {len(issues)} 个疑似幻觉（扣分 {penalty:.2f}）"
        return DimensionScore(
            metric=EvaluationMetric.HALLUCINATION,
            score=score,
            weight=self.config.get_weight(EvaluationMetric.HALLUCINATION),            threshold=threshold,
            reason=reason,
            details={"issues": issues, "issue_count": len(issues), "strictness": self.strictness},
        )

    def detect(
        self,
        output_text: str,
        goal: str = "",
        context_data: dict = None,
        unsupported_apis: list = None,
    ) -> list:
        """测试期望的 API：返回 Issue 列表。"""
        return self.detect_text(
            output_text,
            goal,
            context_data or {},
            unsupported_apis or [],
        )

    def detect_text(
        self,
        text: str,
        goal_description: str = "",
        context_data: dict = None,
        unsupported_apis: list = None,
    ) -> list:
        """文本幻觉检测（返回 Issue 列表）。"""
        if not text:
            return []
        context_data = context_data or {}
        unsupported_apis = unsupported_apis or []
        issues: List[Issue] = []

        # 1. 虚构路径检测（所有 strictness 级别）
        issues.extend(self._detect_fake_paths(text))

        # 2. 离谱数字检测（所有 strictness 级别）
        issues.extend(self._detect_absurd_numbers(text))

        if self.strictness in ("medium", "high"):
            # 3. 自相矛盾检测
            issues.extend(self._detect_contradictions(text))

            # 4. 过度自信检测
            issues.extend(self._detect_overconfidence(text))

        if self.strictness == "high":
            # 5. 虚构 API/方法名检测
            issues.extend(self._detect_fake_apis(text))

        # 6. 自定义 unsupported APIs 检测
        for api in unsupported_apis:
            if api in text:
                issues.append(Issue(
                    code="HALLUCINATION_UNSUPPORTED_API",
                    severity=Severity.MAJOR if self.strictness == "high" else Severity.CRITICAL,
                    message=f"检测到不支持的 API: '{api}'",
                    metric=EvaluationMetric.HALLUCINATION,
                    suggestion=f"'{api}' 可能不存在，请使用已验证的 API",
                    evidence=api,
                    score_penalty=0.15,
                ))

        # 7. False API version 检测 (如 "Python 2.5 引入了 asyncio")
        version_issues = self._check_false_versions(text)
        issues.extend(version_issues)

        return issues

    # ------------------------------------------------------------------
    # 检测方法
    # ------------------------------------------------------------------

    def _detect_fake_paths(self, text: str) -> List[Issue]:
        """检测虚构文件路径。"""
        issues: List[Issue] = []
        lines = text.split("\n")

        for line_no, line in enumerate(lines, 1):
            for pattern in FAKE_PATH_PATTERNS:
                for match in pattern.finditer(line):
                    matched = match.group(0)
                    issues.append(Issue(
                        code="HALLUCINATION_FAKE_PATH",
                        severity=Severity.MINOR,
                        message=f"疑似虚构路径: {matched}",
                        metric=EvaluationMetric.HALLUCINATION,
                        suggestion="使用真实文件路径或标注为示例",
                        location=f"line {line_no}",
                        evidence=line.strip()[:120],
                        score_penalty=0.05,
                    ))

        return issues

    def _detect_absurd_numbers(self, text: str) -> List[Issue]:
        """检测离谱数字（>100% 成功率等）。"""
        issues: List[Issue] = []
        for pattern in ABSURD_NUMBER_PATTERNS:
            for match in pattern.finditer(text):
                issues.append(Issue(
                    code="HALLUCINATION_ABSURD_NUMBER",
                    severity=Severity.MINOR,
                    message=f"疑似离谱数据: {match.group(0)}",
                    metric=EvaluationMetric.HALLUCINATION,
                    suggestion="检查数据准确性，成功率不应超过100%",
                    evidence=match.group(0),
                    score_penalty=0.08,
                ))
        return issues

    def _detect_contradictions(self, text: str) -> List[Issue]:
        """检测自相矛盾（简化版：检测同一文本中的对立声明）。

        例如："这个函数没有问题" ... "这个函数有bug"
        """
        issues: List[Issue] = []
        contradiction_pairs = [
            (re.compile(r"没有(问题|错误|bug|报错)", re.IGNORECASE),
             re.compile(r"(有问题|错误|bug|报错)", re.IGNORECASE)),
            (re.compile(r"成功", re.IGNORECASE),
             re.compile(r"失败", re.IGNORECASE)),
            (re.compile(r"正确", re.IGNORECASE),
             re.compile(r"错误", re.IGNORECASE)),
            (re.compile(r"可以正常", re.IGNORECASE),
             re.compile(r"无法|不能|不可以", re.IGNORECASE)),
        ]

        for pos_pat, neg_pat in contradiction_pairs:
            pos_match = pos_pat.search(text)
            neg_match = neg_pat.search(text)
            if pos_match and neg_match:
                issues.append(Issue(
                    code="HALLUCINATION_CONTRADICTION",
                    severity=Severity.MAJOR,
                    message=f"检测到可能矛盾: '{pos_match.group(0)}' vs '{neg_match.group(0)}'",
                    metric=EvaluationMetric.HALLUCINATION,
                    suggestion="检查文本逻辑一致性",
                    evidence=f"{pos_match.group(0)} ... {neg_match.group(0)}",
                    score_penalty=0.15,
                ))
                break  # 每对只报一次

        return issues

    def _detect_overconfidence(self, text: str) -> List[Issue]:
        """检测过度自信表述。"""
        issues: List[Issue] = []
        for pattern in OVERCONFIDENCE_PATTERNS:
            for match in pattern.finditer(text):
                # 检查是否在代码块/引号中（减分）
                issues.append(Issue(
                    code="HALLUCINATION_OVERCONFIDENCE",
                    severity=Severity.INFO,
                    message=f"过度自信表述: '{match.group(0)}'",
                    metric=EvaluationMetric.HALLUCINATION,
                    suggestion="避免绝对化表述，使用更客观的语言",
                    evidence=match.group(0),
                    score_penalty=0.03,
                ))
        return issues

    def _detect_fake_apis(self, text: str) -> List[Issue]:
        """检测虚构的 API/方法名。"""
        issues: List[Issue] = []
        for pattern in FAKE_API_PATTERNS:
            for match in pattern.finditer(text):
                issues.append(Issue(
                    code="HALLUCINATION_FAKE_API",
                    severity=Severity.MINOR,
                    message=f"疑似虚构 API: '{match.group(0)}'",
                    metric=EvaluationMetric.HALLUCINATION,
                    suggestion="使用真实 API 名称或标注为示例",
                    evidence=match.group(0),
                    score_penalty=0.08,
                ))
        return issues

    @staticmethod
    def _check_false_versions(text: str) -> list:
        """检测假版本声明，如 'Python 2.5 引入了 asyncio'。"""
        issues = []
        false_versions = [
            (r"Python\s*2\.\d+\s*引入了\s*async", Severity.MAJOR, "asyncio 是 Python 3.4+ 引入的"),
            (r"Python\s*2\.\d+\s*引入了\s*[a-z]", Severity.MINOR, None),
        ]
        for pattern, severity, hint in false_versions:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                issues.append(Issue(
                    code="HALLUCINATION_FALSE_API_VERSION",
                    severity=severity,
                    message=f"疑似版本声明错误: '{match.group(0)}'",
                    metric=EvaluationMetric.HALLUCINATION,
                    suggestion=hint or "验证 API 版本信息的准确性",
                    evidence=match.group(0),
                    score_penalty=0.1,
                ))
        return issues
