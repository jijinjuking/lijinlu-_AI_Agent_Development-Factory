"""
预置工作流模板库 — 覆盖常用软件工厂场景

模板 ID 命名规范: {category}_{variant}
"""

from app.runtime.execution_engine.workflow_schema import (
    EdgeSpec,
    NodeSpec,
    NodeType,
    WorkflowSpec,
)
from app.runtime.planner.models import (
    ParameterSlot,
    TemplateCategory,
    WorkflowTemplate,
)


# ============================================================================
# 1. 代码审查 (code_review_v1)
# ============================================================================

CODE_REVIEW_SPEC = WorkflowSpec(
    name="{{task_name}} 代码审查",
    description="对 {{target_branch}} 分支的代码变更进行 AI 审查",
    nodes=[
        NodeSpec(id="start", type=NodeType.START, label="开始"),
        NodeSpec(
            id="load_diff",
            type=NodeType.TOOL,
            label="加载代码变更",
            config={
                "tool_name": "git_diff",
                "args_template": {"branch": "{{target_branch}}", "base": "{{base_branch}}"},
            },
        ),
        NodeSpec(
            id="analyze",
            type=NodeType.LLM,
            label="AI 代码分析",
            config={
                "system_prompt": "你是资深代码审查专家。审查以下代码变更，关注：逻辑错误、安全漏洞、性能问题、代码风格。",
                "model": "{{model_name}}",
                "temperature": 0.2,
            },
        ),
        NodeSpec(
            id="run_tests",
            type=NodeType.TOOL,
            label="运行测试",
            config={
                "tool_name": "run_tests",
                "args_template": {"scope": "changed"},
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
                "message": "代码审查完成，测试全部通过。是否合并？",
                "timeout_seconds": 3600,
            },
        ),
        NodeSpec(id="end", type=NodeType.END, label="结束"),
    ],
    edges=[
        EdgeSpec(source="start", target="load_diff"),
        EdgeSpec(source="load_diff", target="analyze"),
        EdgeSpec(source="analyze", target="run_tests"),
        EdgeSpec(source="run_tests", target="check_result"),
        EdgeSpec(source="check_result", target="request_approval", condition="true"),
        EdgeSpec(source="check_result", target="end", condition="false"),
        EdgeSpec(source="request_approval", target="end"),
    ],
)

CODE_REVIEW_TEMPLATE = WorkflowTemplate(
    id="code_review_v1",
    name="代码审查",
    description="对代码变更进行 AI 审查 + 自动化测试 + 人工确认",
    category=TemplateCategory.CODE_REVIEW,
    trigger_keywords=["代码审查", "code review", "审查代码", "review pr", "pull request"],
    trigger_patterns=["审查", "review", "PR", "合并前检查"],
    min_complexity=2,
    max_complexity=6,
    spec=CODE_REVIEW_SPEC,
    parameter_slots=[
        ParameterSlot(name="task_name", description="任务名称", default="PR"),
        ParameterSlot(name="target_branch", description="目标分支", default="main"),
        ParameterSlot(name="base_branch", description="基准分支", default="develop"),
        ParameterSlot(name="model_name", description="审查模型", default="gpt-4"),
    ],
    tags=["review", "quality", "merge"],
    estimated_nodes=7,
    estimated_tokens=3000,
)


# ============================================================================
# 2. 代码生成 (code_generation_v1)
# ============================================================================

CODE_GEN_SPEC = WorkflowSpec(
    name="{{task_name}} 代码生成",
    description="根据需求生成代码: {{requirement}}",
    nodes=[
        NodeSpec(id="start", type=NodeType.START, label="开始"),
        NodeSpec(
            id="understand_req",
            type=NodeType.LLM,
            label="理解需求",
            config={
                "system_prompt": "分析以下需求，提取核心功能点和约束条件。",
                "model": "{{model_name}}",
                "temperature": 0.1,
            },
        ),
        NodeSpec(
            id="design",
            type=NodeType.LLM,
            label="设计方案",
            config={
                "system_prompt": "根据需求分析结果，设计代码架构和模块划分。输出方案概要。",
                "model": "{{model_name}}",
                "temperature": 0.2,
            },
        ),
        NodeSpec(
            id="generate_code",
            type=NodeType.LLM,
            label="生成代码",
            config={
                "system_prompt": "你是一名{{language}}开发者。根据设计方案生成简洁、可维护的代码。",
                "model": "{{model_name}}",
                "temperature": 0.1,
            },
        ),
        NodeSpec(
            id="validate",
            type=NodeType.TOOL,
            label="代码验证",
            config={
                "tool_name": "lint_and_format",
                "args_template": {},
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
            label="检查结果",
            config={
                "expression": "state.get('error_count') == 0",
            },
        ),
        NodeSpec(
            id="fix_errors",
            type=NodeType.LLM,
            label="修复错误",
            config={
                "system_prompt": "修复以下代码中的错误。",
                "model": "{{model_name}}",
                "temperature": 0.1,
            },
        ),
        NodeSpec(id="end", type=NodeType.END, label="结束"),
    ],
    edges=[
        EdgeSpec(source="start", target="understand_req"),
        EdgeSpec(source="understand_req", target="design"),
        EdgeSpec(source="design", target="generate_code"),
        EdgeSpec(source="generate_code", target="validate"),
        EdgeSpec(source="validate", target="run_tests"),
        EdgeSpec(source="run_tests", target="check_result"),
        EdgeSpec(source="check_result", target="end", condition="true"),
        EdgeSpec(source="check_result", target="fix_errors", condition="false"),
        EdgeSpec(source="fix_errors", target="run_tests"),
    ],
)

CODE_GEN_TEMPLATE = WorkflowTemplate(
    id="code_generation_v1",
    name="代码生成",
    description="需求分析 → 方案设计 → 代码生成 → 验证测试 → 修复循环",
    category=TemplateCategory.CODE_GENERATION,
    trigger_keywords=["代码生成", "生成代码", "写代码", "实现功能", "开发"],
    trigger_patterns=["写一个", "实现", "开发", "创建一个"],
    min_complexity=3,
    max_complexity=8,
    spec=CODE_GEN_SPEC,
    parameter_slots=[
        ParameterSlot(name="task_name", description="任务名称", default="功能开发"),
        ParameterSlot(name="requirement", description="功能需求描述", default="未指定"),
        ParameterSlot(name="language", description="编程语言", default="Python"),
        ParameterSlot(name="model_name", description="生成模型", default="gpt-4"),
    ],
    tags=["code", "generation", "development"],
    estimated_nodes=8,
    estimated_tokens=5000,
)


# ============================================================================
# 3. Bug 修复 (bug_fix_v1)
# ============================================================================

BUG_FIX_SPEC = WorkflowSpec(
    name="{{task_name}} Bug 修复",
    description="定位并修复: {{bug_description}}",
    nodes=[
        NodeSpec(id="start", type=NodeType.START, label="开始"),
        NodeSpec(
            id="gather_context",
            type=NodeType.TOOL,
            label="收集上下文",
            config={
                "tool_name": "gather_bug_context",
                "args_template": {"error_log": "{{error_log}}"},
            },
        ),
        NodeSpec(
            id="analyze_bug",
            type=NodeType.LLM,
            label="分析 Bug",
            config={
                "system_prompt": "你是一名 Bug 分析专家。根据错误日志和上下文，定位根因。",
                "model": "{{model_name}}",
                "temperature": 0.1,
            },
        ),
        NodeSpec(
            id="propose_fix",
            type=NodeType.LLM,
            label="提出修复方案",
            config={
                "system_prompt": "根据根因分析，提出最小化的修复方案。只改必要代码。",
                "model": "{{model_name}}",
                "temperature": 0.1,
            },
        ),
        NodeSpec(
            id="apply_fix",
            type=NodeType.TOOL,
            label="应用修复",
            config={
                "tool_name": "apply_patch",
                "args_template": {},
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
            label="验证修复",
            config={
                "expression": "state.get('error_count') == 0",
            },
        ),
        NodeSpec(
            id="regression_test",
            type=NodeType.TOOL,
            label="回归测试",
            config={
                "tool_name": "run_tests",
                "args_template": {"scope": "full"},
            },
        ),
        NodeSpec(id="end", type=NodeType.END, label="结束"),
    ],
    edges=[
        EdgeSpec(source="start", target="gather_context"),
        EdgeSpec(source="gather_context", target="analyze_bug"),
        EdgeSpec(source="analyze_bug", target="propose_fix"),
        EdgeSpec(source="propose_fix", target="apply_fix"),
        EdgeSpec(source="apply_fix", target="run_tests"),
        EdgeSpec(source="run_tests", target="check_result"),
        EdgeSpec(source="check_result", target="regression_test", condition="true"),
        EdgeSpec(source="check_result", target="analyze_bug", condition="false"),
        EdgeSpec(source="regression_test", target="end"),
    ],
)

BUG_FIX_TEMPLATE = WorkflowTemplate(
    id="bug_fix_v1",
    name="Bug 修复",
    description="收集上下文 → 根因分析 → 修复方案 → 验证 → 回归测试",
    category=TemplateCategory.BUG_FIX,
    trigger_keywords=["bug", "修复", "修bug", "fix bug", "报错", "错误"],
    trigger_patterns=["bug", "错误", "报错", "崩溃", "不工作"],
    min_complexity=2,
    max_complexity=7,
    spec=BUG_FIX_SPEC,
    parameter_slots=[
        ParameterSlot(name="task_name", description="任务名称", default="Bug修复"),
        ParameterSlot(name="bug_description", description="Bug 描述", default="未知错误"),
        ParameterSlot(name="error_log", description="错误日志", default=""),
        ParameterSlot(name="model_name", description="分析模型", default="gpt-4"),
    ],
    tags=["bug", "fix", "debug"],
    estimated_nodes=8,
    estimated_tokens=4000,
)


# ============================================================================
# 4. 数据分析 (data_analysis_v1)
# ============================================================================

DATA_ANALYSIS_SPEC = WorkflowSpec(
    name="{{task_name}} 数据分析",
    description="分析数据并生成报告: {{data_source}}",
    nodes=[
        NodeSpec(id="start", type=NodeType.START, label="开始"),
        NodeSpec(
            id="load_data",
            type=NodeType.TOOL,
            label="加载数据",
            config={
                "tool_name": "load_data",
                "args_template": {"source": "{{data_source}}", "format": "{{format}}"},
            },
        ),
        NodeSpec(
            id="clean_data",
            type=NodeType.TOOL,
            label="数据清洗",
            config={
                "tool_name": "clean_data",
                "args_template": {},
            },
        ),
        NodeSpec(
            id="explore",
            type=NodeType.LLM,
            label="数据探索",
            config={
                "system_prompt": "分析数据特征，发现模式、异常和关联关系。",
                "model": "{{model_name}}",
                "temperature": 0.2,
            },
        ),
        NodeSpec(
            id="visualize",
            type=NodeType.TOOL,
            label="可视化",
            config={
                "tool_name": "create_visualization",
                "args_template": {"chart_type": "{{chart_type}}"},
            },
        ),
        NodeSpec(
            id="generate_report",
            type=NodeType.LLM,
            label="生成报告",
            config={
                "system_prompt": "基于数据分析结果生成结构化报告，包含：关键发现、洞察建议、行动推荐。",
                "model": "{{model_name}}",
                "temperature": 0.3,
            },
        ),
        NodeSpec(id="end", type=NodeType.END, label="结束"),
    ],
    edges=[
        EdgeSpec(source="start", target="load_data"),
        EdgeSpec(source="load_data", target="clean_data"),
        EdgeSpec(source="clean_data", target="explore"),
        EdgeSpec(source="explore", target="visualize"),
        EdgeSpec(source="visualize", target="generate_report"),
        EdgeSpec(source="generate_report", target="end"),
    ],
)

DATA_ANALYSIS_TEMPLATE = WorkflowTemplate(
    id="data_analysis_v1",
    name="数据分析",
    description="数据加载 → 清洗 → 探索 → 可视化 → 报告",
    category=TemplateCategory.DATA_ANALYSIS,
    trigger_keywords=["数据分析", "分析数据", "数据报告", "可视化", "报表"],
    trigger_patterns=["分析", "数据", "图表", "趋势"],
    min_complexity=2,
    max_complexity=8,
    spec=DATA_ANALYSIS_SPEC,
    parameter_slots=[
        ParameterSlot(name="task_name", description="任务名称", default="数据分析"),
        ParameterSlot(name="data_source", description="数据源", default="data.csv"),
        ParameterSlot(name="format", description="数据格式", default="csv"),
        ParameterSlot(name="chart_type", description="图表类型", default="auto"),
        ParameterSlot(name="model_name", description="分析模型", default="gpt-4"),
    ],
    tags=["data", "analysis", "visualization"],
    estimated_nodes=6,
    estimated_tokens=3500,
)


# ============================================================================
# 5. 部署 (deploy_v1)
# ============================================================================

DEPLOY_SPEC = WorkflowSpec(
    name="{{task_name}} 部署",
    description="部署到 {{environment}} 环境",
    nodes=[
        NodeSpec(id="start", type=NodeType.START, label="开始"),
        NodeSpec(
            id="build",
            type=NodeType.TOOL,
            label="构建",
            config={
                "tool_name": "build",
                "args_template": {"env": "{{environment}}"},
            },
        ),
        NodeSpec(
            id="run_tests",
            type=NodeType.TOOL,
            label="运行测试",
            config={
                "tool_name": "run_tests",
                "args_template": {"scope": "pre_deploy"},
            },
        ),
        NodeSpec(
            id="check_tests",
            type=NodeType.CONDITION,
            label="测试通过?",
            config={
                "expression": "state.get('error_count') == 0",
            },
        ),
        NodeSpec(
            id="deploy",
            type=NodeType.TOOL,
            label="部署",
            config={
                "tool_name": "deploy",
                "args_template": {
                    "env": "{{environment}}",
                    "strategy": "{{deploy_strategy}}",
                },
            },
        ),
        NodeSpec(
            id="health_check",
            type=NodeType.TOOL,
            label="健康检查",
            config={
                "tool_name": "health_check",
                "args_template": {"env": "{{environment}}"},
            },
        ),
        NodeSpec(
            id="check_health",
            type=NodeType.CONDITION,
            label="健康检查通过?",
            config={
                "expression": "state.get('workflow_status') == 'completed'",
            },
        ),
        NodeSpec(
            id="rollback",
            type=NodeType.TOOL,
            label="回滚",
            config={
                "tool_name": "rollback",
                "args_template": {"env": "{{environment}}"},
            },
        ),
        NodeSpec(
            id="notify",
            type=NodeType.TOOL,
            label="通知",
            config={
                "tool_name": "send_notification",
                "args_template": {"channel": "{{notify_channel}}"},
            },
        ),
        NodeSpec(id="end", type=NodeType.END, label="结束"),
    ],
    edges=[
        EdgeSpec(source="start", target="build"),
        EdgeSpec(source="build", target="run_tests"),
        EdgeSpec(source="run_tests", target="check_tests"),
        EdgeSpec(source="check_tests", target="deploy", condition="true"),
        EdgeSpec(source="check_tests", target="end", condition="false"),
        EdgeSpec(source="deploy", target="health_check"),
        EdgeSpec(source="health_check", target="check_health"),
        EdgeSpec(source="check_health", target="notify", condition="true"),
        EdgeSpec(source="check_health", target="rollback", condition="false"),
        EdgeSpec(source="rollback", target="notify"),
        EdgeSpec(source="notify", target="end"),
    ],
)

DEPLOY_TEMPLATE = WorkflowTemplate(
    id="deploy_v1",
    name="部署",
    description="构建 → 测试 → 部署 → 健康检查 → 失败回滚 + 通知",
    category=TemplateCategory.DEPLOY,
    trigger_keywords=["部署", "发布", "上线", "deploy", "release"],
    trigger_patterns=["部署到", "发布", "上线", "deploy to"],
    min_complexity=3,
    max_complexity=7,
    spec=DEPLOY_SPEC,
    parameter_slots=[
        ParameterSlot(name="task_name", description="任务名称", default="部署"),
        ParameterSlot(name="environment", description="部署环境", default="staging",
                       options=["staging", "production", "dev"]),
        ParameterSlot(name="deploy_strategy", description="部署策略", default="rolling",
                       options=["rolling", "blue_green", "canary"]),
        ParameterSlot(name="notify_channel", description="通知渠道", default="slack"),
    ],
    tags=["deploy", "ops", "ci_cd"],
    estimated_nodes=9,
    estimated_tokens=2500,
)


# ============================================================================
# 6. 问答 (qa_v1)
# ============================================================================

QA_SPEC = WorkflowSpec(
    name="{{task_name}} 问答",
    description="回答: {{question}}",
    nodes=[
        NodeSpec(id="start", type=NodeType.START, label="开始"),
        NodeSpec(
            id="understand",
            type=NodeType.LLM,
            label="理解问题",
            config={
                "system_prompt": "解析用户问题，提取关键概念和意图。",
                "model": "{{model_name}}",
                "temperature": 0.1,
            },
        ),
        NodeSpec(
            id="search_knowledge",
            type=NodeType.TOOL,
            label="搜索知识库",
            config={
                "tool_name": "search_knowledge_base",
                "args_template": {"top_k": "{{top_k}}"},
            },
        ),
        NodeSpec(
            id="synthesize",
            type=NodeType.LLM,
            label="综合回答",
            config={
                "system_prompt": "基于检索的知识，综合生成清晰、准确的回答。如知识库无法覆盖，诚实说明。",
                "model": "{{model_name}}",
                "temperature": 0.3,
            },
        ),
        NodeSpec(
            id="quality_check",
            type=NodeType.LLM,
            label="质量检查",
            config={
                "system_prompt": "检查回答是否准确、完整、无幻觉。如发现问题，标注修正。",
                "model": "{{model_name}}",
                "temperature": 0.1,
            },
        ),
        NodeSpec(
            id="need_web_search",
            type=NodeType.CONDITION,
            label="需要联网搜索?",
            config={
                "expression": "state.get('metadata', {}).get('need_web_search', False)",
            },
        ),
        NodeSpec(
            id="web_search",
            type=NodeType.TOOL,
            label="联网搜索",
            config={
                "tool_name": "web_search",
                "args_template": {},
            },
        ),
        NodeSpec(id="end", type=NodeType.END, label="结束"),
    ],
    edges=[
        EdgeSpec(source="start", target="understand"),
        EdgeSpec(source="understand", target="search_knowledge"),
        EdgeSpec(source="search_knowledge", target="synthesize"),
        EdgeSpec(source="synthesize", target="quality_check"),
        EdgeSpec(source="quality_check", target="need_web_search"),
        EdgeSpec(source="need_web_search", target="web_search", condition="true"),
        EdgeSpec(source="need_web_search", target="end", condition="false"),
        EdgeSpec(source="web_search", target="synthesize"),
    ],
)

QA_TEMPLATE = WorkflowTemplate(
    id="qa_v1",
    name="问答",
    description="理解问题 → 搜索知识库 → 综合回答 → 质量检查 → 补充搜索",
    category=TemplateCategory.QA,
    trigger_keywords=["问答", "提问", "问题", "查询", "帮我查", "怎么"],
    trigger_patterns=["什么是", "如何", "怎么", "帮我查", "解释"],
    min_complexity=1,
    max_complexity=5,
    spec=QA_SPEC,
    parameter_slots=[
        ParameterSlot(name="task_name", description="任务名称", default="问答"),
        ParameterSlot(name="question", description="问题内容", default="请描述你的问题"),
        ParameterSlot(name="model_name", description="回答模型", default="gpt-4"),
        ParameterSlot(name="top_k", description="检索数量", default="5"),
    ],
    tags=["qa", "knowledge", "search"],
    estimated_nodes=7,
    estimated_tokens=2500,
)


# ============================================================================
# 7. 重构 (refactor_v1)
# ============================================================================

REFACTOR_SPEC = WorkflowSpec(
    name="{{task_name}} 代码重构",
    description="重构 {{target_path}} 以提高 {{refactor_goal}}",
    nodes=[
        NodeSpec(id="start", type=NodeType.START, label="开始"),
        NodeSpec(
            id="analyze_code",
            type=NodeType.TOOL,
            label="代码分析",
            config={
                "tool_name": "analyze_code",
                "args_template": {"path": "{{target_path}}"},
            },
        ),
        NodeSpec(
            id="identify_smells",
            type=NodeType.LLM,
            label="识别坏味道",
            config={
                "system_prompt": "分析代码，识别代码坏味道：重复代码、长方法、耦合过紧、命名不当等。",
                "model": "{{model_name}}",
                "temperature": 0.2,
            },
        ),
        NodeSpec(
            id="propose_refactor",
            type=NodeType.LLM,
            label="提出重构方案",
            config={
                "system_prompt": "基于代码坏味道，提出最小化、安全的重构方案。遵循{{refactor_goal}}原则。",
                "model": "{{model_name}}",
                "temperature": 0.2,
            },
        ),
        NodeSpec(
            id="apply_refactor",
            type=NodeType.TOOL,
            label="应用重构",
            config={
                "tool_name": "apply_refactor",
                "args_template": {},
            },
        ),
        NodeSpec(
            id="run_tests",
            type=NodeType.TOOL,
            label="运行测试",
            config={
                "tool_name": "run_tests",
                "args_template": {"scope": "full"},
            },
        ),
        NodeSpec(
            id="check_tests",
            type=NodeType.CONDITION,
            label="测试通过?",
            config={
                "expression": "state.get('error_count') == 0",
            },
        ),
        NodeSpec(
            id="review_diff",
            type=NodeType.LLM,
            label="审查变更",
            config={
                "system_prompt": "审查重构变更，确保行为不变、质量提升。",
                "model": "{{model_name}}",
                "temperature": 0.1,
            },
        ),
        NodeSpec(id="end", type=NodeType.END, label="结束"),
    ],
    edges=[
        EdgeSpec(source="start", target="analyze_code"),
        EdgeSpec(source="analyze_code", target="identify_smells"),
        EdgeSpec(source="identify_smells", target="propose_refactor"),
        EdgeSpec(source="propose_refactor", target="apply_refactor"),
        EdgeSpec(source="apply_refactor", target="run_tests"),
        EdgeSpec(source="run_tests", target="check_tests"),
        EdgeSpec(source="check_tests", target="review_diff", condition="true"),
        EdgeSpec(source="check_tests", target="identify_smells", condition="false"),
        EdgeSpec(source="review_diff", target="end"),
    ],
)

REFACTOR_TEMPLATE = WorkflowTemplate(
    id="refactor_v1",
    name="代码重构",
    description="代码分析 → 坏味道识别 → 重构方案 → 应用 → 测试 → 审查",
    category=TemplateCategory.REFACTOR,
    trigger_keywords=["重构", "refactor", "优化代码", "代码优化"],
    trigger_patterns=["重构", "整理代码", "优化结构"],
    min_complexity=3,
    max_complexity=8,
    spec=REFACTOR_SPEC,
    parameter_slots=[
        ParameterSlot(name="task_name", description="任务名称", default="代码重构"),
        ParameterSlot(name="target_path", description="目标路径", default="src/"),
        ParameterSlot(name="refactor_goal", description="重构目标", default="可维护性",
                       options=["可维护性", "性能", "可读性", "可测试性"]),
        ParameterSlot(name="model_name", description="分析模型", default="gpt-4"),
    ],
    tags=["refactor", "quality", "maintenance"],
    estimated_nodes=8,
    estimated_tokens=4500,
)


# ============================================================================
# 构建预置模板库
# ============================================================================

def create_default_template_library():
    """创建预置模板库"""
    from app.runtime.planner.models import TemplateLibrary

    library = TemplateLibrary()
    library.register(CODE_REVIEW_TEMPLATE)
    library.register(CODE_GEN_TEMPLATE)
    library.register(BUG_FIX_TEMPLATE)
    library.register(DATA_ANALYSIS_TEMPLATE)
    library.register(DEPLOY_TEMPLATE)
    library.register(QA_TEMPLATE)
    library.register(REFACTOR_TEMPLATE)
    return library


# 全局默认模板库
default_template_library = create_default_template_library()
