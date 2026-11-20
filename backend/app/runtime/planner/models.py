"""
Planner Agent Models — 动态 Workflow 生成的类型定义

核心类型:
- PlanningGoal: 用户目标 → 结构化意图
- WorkflowTemplate: 可复用的参数化工作流模板
- TemplateLibrary: 模板注册与匹配
- PlanningResult: 规划输出（生成的 WorkflowSpec + 元数据）
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from app.runtime.execution_engine.workflow_schema import WorkflowSpec


# ============================================================================
# Planning Strategy
# ============================================================================

class PlanningStrategy(str, Enum):
    """规划策略"""
    TEMPLATE_MATCH = "template_match"      # 纯模板匹配（目标完全匹配模板）
    LLM_GENERATE = "llm_generate"          # 全 LLM 生成（无匹配模板时）
    HYBRID = "hybrid"                      # 模板 + LLM 细化（默认）
    QUERY_EXPANSION = "query_expansion"    # 多目标拆解 + 编排


# ============================================================================
# Template Type
# ============================================================================

class TemplateCategory(str, Enum):
    """模板分类"""
    CODE_REVIEW = "code_review"
    CODE_GENERATION = "code_generation"
    BUG_FIX = "bug_fix"
    DATA_ANALYSIS = "data_analysis"
    DEPLOY = "deploy"
    QA = "qa"
    REFACTOR = "refactor"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    CUSTOM = "custom"


# ============================================================================
# Planning Goal
# ============================================================================

@dataclass
class PlanningGoal:
    """结构化的规划目标"""
    raw_text: str
    category: Optional[TemplateCategory] = None
    complexity: int = 3  # 1~10
    keywords: List[str] = field(default_factory=list)
    entities: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)

    def hash(self) -> str:
        """生成目标摘要哈希（用于缓存）"""
        content = f"{self.raw_text}|{self.category or ''}|{self.complexity}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


# ============================================================================
# Workflow Template
# ============================================================================

@dataclass
class ParameterSlot:
    """模板参数槽 — 模板中使用 {{param_name}} 占位"""
    name: str
    description: str
    param_type: str = "string"  # string | int | float | bool | json
    default: Any = None
    required: bool = True
    options: Optional[List[str]] = None  # 枚举值时用


@dataclass
class WorkflowTemplate:
    """工作流模板 — 带参数槽的工作流骨架"""
    id: str
    name: str
    description: str
    category: TemplateCategory
    version: str = "1.0"
    # 匹配信号
    trigger_keywords: List[str] = field(default_factory=list)
    trigger_patterns: List[str] = field(default_factory=list)  # regex patterns
    min_complexity: int = 1
    max_complexity: int = 10
    # WorkflowSpec 骨架（支持参数占位）
    spec: Optional[WorkflowSpec] = None
    # 参数槽
    parameter_slots: List[ParameterSlot] = field(default_factory=list)
    # 元数据
    tags: List[str] = field(default_factory=list)
    estimated_nodes: int = 0
    estimated_tokens: int = 0  # 预估 LLM 消耗

    def match_score(self, goal: PlanningGoal) -> Tuple[float, Dict[str, Any]]:
        """计算目标与模板的匹配度 (0~1)，返回 (分数, 匹配详情)"""
        score = 0.0
        details: Dict[str, Any] = {}

        # 1. 类别匹配（如果 goal 已分类）
        if goal.category and goal.category == self.category:
            score += 0.4
            details["category_match"] = 0.4

        # 2. 关键词匹配
        if self.trigger_keywords and goal.keywords:
            kw_set = set(k.lower() for k in self.trigger_keywords)
            matched = kw_set & set(k.lower() for k in goal.keywords)
            if matched:
                kw_score = min(len(matched) / max(len(kw_set), 1), 1.0) * 0.3
                score += kw_score
                details["keyword_match"] = kw_score

        # 3. 模式匹配（简单子串匹配，不用 regex 保持 Python 沙箱兼容）
        if self.trigger_patterns and goal.raw_text:
            pattern_matches = sum(
                1 for p in self.trigger_patterns
                if p.lower() in goal.raw_text.lower()
            )
            if pattern_matches:
                pattern_score = min(pattern_matches / max(len(self.trigger_patterns), 1), 1.0) * 0.2
                score += pattern_score
                details["pattern_match"] = pattern_score

        # 4. 复杂度匹配
        if self.min_complexity <= goal.complexity <= self.max_complexity:
            score += 0.1
            details["complexity_match"] = 0.1

        return min(score, 1.0), details

    def apply_parameters(self, params: Dict[str, Any]) -> WorkflowSpec:
        """将参数值填入模板，返回具体的 WorkflowSpec"""
        if self.spec is None:
            raise ValueError(f"Template '{self.id}' has no spec")

        spec = self.spec.model_copy(deep=True)

        # Define defaults for each parameter
        defaults: Dict[str, Any] = {}
        for slot in self.parameter_slots:
            if slot.name not in params and slot.default is not None:
                defaults[slot.name] = slot.default

        merged_params = {**defaults, **params}

        def _replace_in_value(val: Any) -> Any:
            """递归替换值中的 {{param}} 占位"""
            if isinstance(val, str):
                result = val
                for pn, pv in merged_params.items():
                    placeholder = f"{{{{{pn}}}}}"
                    result = result.replace(placeholder, str(pv))
                return result
            elif isinstance(val, dict):
                return {k: _replace_in_value(v) for k, v in val.items()}
            elif isinstance(val, list):
                return [_replace_in_value(item) for item in val]
            return val

        # Apply to node configs
        for node in spec.nodes:
            node.config = _replace_in_value(node.config)
            node.label = _replace_in_value(node.label)

        # Apply to spec name/description
        spec.name = _replace_in_value(spec.name)
        spec.description = _replace_in_value(spec.description)

        return spec


# ============================================================================
# Template Library
# ============================================================================

class TemplateLibrary:
    """模板注册与管理"""

    def __init__(self):
        self._templates: Dict[str, WorkflowTemplate] = {}

    def register(self, template: WorkflowTemplate) -> None:
        """注册模板"""
        self._templates[template.id] = template

    def get(self, template_id: str) -> Optional[WorkflowTemplate]:
        """获取模板"""
        return self._templates.get(template_id)

    def list_all(self) -> List[WorkflowTemplate]:
        """列出所有模板"""
        return list(self._templates.values())

    def list_by_category(self, category: TemplateCategory) -> List[WorkflowTemplate]:
        """按分类列出模板"""
        return [t for t in self._templates.values() if t.category == category]

    def search(self, goal: PlanningGoal, min_score: float = 0.2) -> List[Tuple[WorkflowTemplate, float]]:
        """搜索匹配模板，返回 (模板, 分数)，按分数降序"""
        results: List[Tuple[WorkflowTemplate, float]] = []
        for template in self._templates.values():
            score, _ = template.match_score(goal)
            if score >= min_score:
                results.append((template, score))
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def best_match(self, goal: PlanningGoal, min_score: float = 0.3) -> Optional[WorkflowTemplate]:
        """返回最佳匹配模板（如有）"""
        results = self.search(goal, min_score)
        return results[0][0] if results else None

    def __len__(self) -> int:
        return len(self._templates)

    def __contains__(self, template_id: str) -> bool:
        return template_id in self._templates


# ============================================================================
# Planning Result
# ============================================================================

@dataclass
class PlanningResult:
    """规划结果"""
    workflow_spec: WorkflowSpec
    strategy: PlanningStrategy
    template_id: Optional[str] = None  # 使用的模板 ID（如有）
    template_score: float = 0.0
    # 元数据
    estimated_nodes: int = 0
    estimated_tokens: int = 0
    estimated_cost: float = 0.0
    confidence: float = 1.0  # 0~1，规划置信度
    # 生成信息
    generated_by: str = "planner_agent"
    generation_time_ms: float = 0.0
    warnings: List[str] = field(default_factory=list)

    @property
    def is_template_based(self) -> bool:
        return self.template_id is not None
