"""
Planner Agent — 动态 Workflow 生成引擎 (W17)

职责：
- 接收用户目标描述
- 模板匹配 + LLM 细化
- 动态生成 WorkflowSpec（禁止写死 graph.add_edge()）
- 验证输出正确性
"""

from app.runtime.planner.models import (
    ParameterSlot,
    PlanningGoal,
    PlanningResult,
    PlanningStrategy,
    TemplateCategory,
    TemplateLibrary,
    WorkflowTemplate,
)
from app.runtime.planner.templates import (
    create_default_template_library,
    default_template_library,
)
from app.runtime.planner.validator import (
    WorkflowValidator,
    ValidationError,
    ValidationResult,
    validate_workflow,
)
from app.runtime.planner.planner_agent import (
    PlannerAgent,
    classify_intent,
    get_default_planner,
    CATEGORY_KEYWORDS,
)

__all__ = [
    # Models
    "ParameterSlot",
    "PlanningGoal",
    "PlanningResult",
    "PlanningStrategy",
    "TemplateCategory",
    "TemplateLibrary",
    "WorkflowTemplate",
    # Templates
    "create_default_template_library",
    "default_template_library",
    # Validator
    "WorkflowValidator",
    "ValidationError",
    "ValidationResult",
    "validate_workflow",
    # Agent
    "PlannerAgent",
    "classify_intent",
    "get_default_planner",
    "CATEGORY_KEYWORDS",
]
