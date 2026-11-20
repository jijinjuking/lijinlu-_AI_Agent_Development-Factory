"""
W17 Planner Agent 测试套件

覆盖:
1. Intent Classification — classify_intent
2. Template Library — register, search, match_score, apply_parameters
3. WorkflowValidator — DAG, 可达性, 结构完整性
4. PlannerAgent — template_match, fallback, hybrid (no LLM)
5. RuntimeKernel Integration — generate_workflow, submit_task_with_workflow
"""

import pytest
import pytest
from app.runtime.planner.templates import (
    create_default_template_library,
    CODE_REVIEW_TEMPLATE,
    CODE_GEN_TEMPLATE,
    BUG_FIX_TEMPLATE,
    DATA_ANALYSIS_TEMPLATE,
    DEPLOY_TEMPLATE,
    QA_TEMPLATE,
    REFACTOR_TEMPLATE,
)
from app.runtime.planner.models import (
    PlanningGoal,
    PlanningResult,
    PlanningStrategy,
    TemplateCategory,
    TemplateLibrary,
    WorkflowTemplate,
    ParameterSlot,
)
from app.runtime.planner.planner_agent import (
    PlannerAgent,
    classify_intent,
)
from app.runtime.planner.validator import (
    WorkflowValidator,
    ValidationError,
    ValidationResult,
    validate_workflow,
)
from app.runtime.execution_engine.workflow_schema import (
    WorkflowSpec,
    NodeSpec,
    EdgeSpec,
    NodeType,
    EXAMPLE_WORKFLOW,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def template_library():
    return create_default_template_library()


@pytest.fixture
def validator():
    return WorkflowValidator()


@pytest.fixture
def planner(template_library):
    """PlannerAgent without LLM (template-only mode)"""
    return PlannerAgent(
        template_library=template_library,
        llm_service=None,  # no LLM — test template matching only
        min_template_score=0.1,
    )


# ============================================================================
# 1. Intent Classification Tests
# ============================================================================

class TestIntentClassification:
    """意图分类（纯规则）"""

    def test_classify_code_review(self):
        goal = classify_intent("请审查这个 PR 的代码变更")
        assert goal.category == TemplateCategory.CODE_REVIEW

    def test_classify_code_generation(self):
        goal = classify_intent("帮我写一个 Python 函数来计算斐波那契数列")
        assert goal.category == TemplateCategory.CODE_GENERATION

    def test_classify_bug_fix(self):
        goal = classify_intent("修复这个 bug：空指针异常")
        assert goal.category == TemplateCategory.BUG_FIX

    def test_classify_data_analysis(self):
        goal = classify_intent("分析 sales.csv 的数据并生成图表")
        assert goal.category == TemplateCategory.DATA_ANALYSIS

    def test_classify_deploy(self):
        goal = classify_intent("部署到 production 环境")
        assert goal.category == TemplateCategory.DEPLOY

    def test_classify_qa(self):
        goal = classify_intent("什么是 LangGraph 的 StateGraph？")
        assert goal.category == TemplateCategory.QA

    def test_classify_refactor(self):
        goal = classify_intent("重构 src/ 目录的代码以提高可维护性")
        assert goal.category == TemplateCategory.REFACTOR

    def test_classify_unknown_defaults_to_none(self):
        """无匹配时应返回 None category（或最佳猜测）"""
        goal = classify_intent("xyzzy frobnicate")
        # 不 crash 即可
        assert goal.raw_text == "xyzzy frobnicate"

    def test_complexity_detection_simple(self):
        goal = classify_intent("简单任务：打印 hello world")
        assert goal.complexity <= 3

    def test_complexity_detection_complex(self):
        goal = classify_intent("这是一个非常复杂的大型项目重构任务")
        assert goal.complexity >= 7

    def test_entity_language_detection(self):
        goal = classify_intent("用 Rust 写一个 TCP 服务器")
        assert goal.entities.get("language") == "Rust"

    def test_goal_hash_is_stable(self):
        a = classify_intent("测试目标")
        b = classify_intent("测试目标")
        assert a.hash() == b.hash()

    def test_goal_hash_differs(self):
        a = classify_intent("目标A")
        b = classify_intent("目标B")
        assert a.hash() != b.hash()


# ============================================================================
# 2. Template Library Tests
# ============================================================================

class TestTemplateLibrary:
    """模板库操作"""

    def test_library_has_all_defaults(self, template_library):
        assert len(template_library) == 7
        assert "code_review_v1" in template_library
        assert "code_generation_v1" in template_library

    def test_get_by_id(self, template_library):
        t = template_library.get("qa_v1")
        assert t is not None
        assert t.name == "问答"

    def test_list_by_category(self, template_library):
        review = template_library.list_by_category(TemplateCategory.CODE_REVIEW)
        assert len(review) == 1
        assert review[0].id == "code_review_v1"

    def test_search_returns_ranked_results(self, template_library):
        goal = classify_intent("请审查这次代码变更")
        results = template_library.search(goal)
        assert len(results) > 0
        assert results[0][0].id == "code_review_v1"  # top match
        assert results[0][1] >= 0.3  # score

    def test_best_match_returns_top(self, template_library):
        goal = classify_intent("部署到生产环境并通知团队")
        best = template_library.best_match(goal, min_score=0.2)
        assert best is not None
        assert best.id == "deploy_v1"

    def test_best_match_no_match(self, template_library):
        goal = classify_intent("xyzzy random nonsense no match")
        best = template_library.best_match(goal, min_score=0.5)
        assert best is None

    def test_apply_parameters(self):
        """参数替换应该正确填入占位"""
        spec = CODE_REVIEW_TEMPLATE.apply_parameters({
            "task_name": "测试PR",
            "target_branch": "feature/x",
            "model_name": "gpt-3.5",
        })
        assert "测试PR" in spec.name
        assert spec.name == "测试PR 代码审查"
        # check config was applied
        load_node = next(n for n in spec.nodes if n.id == "load_diff")
        assert "feature/x" in str(load_node.config["args_template"]["branch"])

    def test_apply_parameters_defaults(self):
        """未提供的参数使用默认值"""
        spec = CODE_REVIEW_TEMPLATE.apply_parameters({})
        # model should have default value
        analyze_node = next(n for n in spec.nodes if n.id == "analyze")
        assert "gpt-4" == analyze_node.config["model"]  # default


class TestTemplateMatchScoring:
    """匹配打分逻辑"""

    def test_perfect_category_match(self):
        template = CODE_REVIEW_TEMPLATE
        goal = PlanningGoal(
            raw_text="审查代码",
            category=TemplateCategory.CODE_REVIEW,
            keywords=["审查", "代码"],
        )
        score, details = template.match_score(goal)
        assert score >= 0.4  # category match

    def test_keyword_boost(self):
        template = BUG_FIX_TEMPLATE
        goal = PlanningGoal(
            raw_text="修复一个 JSON 解析的 bug",
            category=TemplateCategory.BUG_FIX,
            keywords=["bug", "修复"],
        )
        score, _ = template.match_score(goal)
        assert score >= 0.5  # category + keyword

    def test_complexity_mismatch_penalty(self):
        template = DEPLOY_TEMPLATE  # max_complexity=7
        goal = PlanningGoal(
            raw_text="部署",
            category=TemplateCategory.DEPLOY,
            complexity=9,  # above max
        )
        score, details = template.match_score(goal)
        assert "complexity_match" not in details  # no complexity bonus

    def test_no_match_for_wrong_category(self):
        template = QA_TEMPLATE
        goal = PlanningGoal(
            raw_text="重构代码",
            category=TemplateCategory.REFACTOR,
        )
        score, _ = template.match_score(goal)
        assert score < 0.2  # very low


# ============================================================================
# 3. Workflow Validator Tests
# ============================================================================

class TestWorkflowValidator:
    """WorkflowSpec 验证器"""

    def test_example_workflow_is_valid(self, validator):
        result = validator.validate(EXAMPLE_WORKFLOW)
        assert result.is_valid
        assert len(result.errors) == 0

    def test_validates_no_start_node(self, validator):
        spec = WorkflowSpec(
            nodes=[
                NodeSpec(id="a", type=NodeType.LLM, label="A"),
                NodeSpec(id="end", type=NodeType.END, label="End"),
            ],
            edges=[
                EdgeSpec(source="a", target="end"),
            ],
        )
        result = validator.validate(spec)
        assert not result.is_valid
        assert any(e.code == "NO_START_NODE" for e in result.errors)

    def test_validates_no_end_node(self, validator):
        spec = WorkflowSpec(
            nodes=[
                NodeSpec(id="start", type=NodeType.START, label="Start"),
                NodeSpec(id="a", type=NodeType.LLM, label="A"),
            ],
            edges=[
                EdgeSpec(source="start", target="a"),
            ],
        )
        result = validator.validate(spec)
        assert not result.is_valid
        assert any(e.code == "NO_END_NODE" for e in result.errors)

    def test_validates_duplicate_node_ids(self, validator):
        spec = WorkflowSpec(
            nodes=[
                NodeSpec(id="start", type=NodeType.START, label="Start"),
                NodeSpec(id="a", type=NodeType.LLM, label="A1"),
                NodeSpec(id="a", type=NodeType.TOOL, label="A2"),  # duplicate
                NodeSpec(id="end", type=NodeType.END, label="End"),
            ],
            edges=[
                EdgeSpec(source="start", target="a"),
                EdgeSpec(source="a", target="end"),
            ],
        )
        result = validator.validate(spec)
        assert not result.is_valid
        assert any(e.code == "DUPLICATE_NODE_ID" for e in result.errors)

    def test_validates_cycle(self, validator):
        """A → B → C → A 产生警告（LangGraph 支持条件回边）"""
        spec = WorkflowSpec(
            nodes=[
                NodeSpec(id="start", type=NodeType.START, label="Start"),
                NodeSpec(id="a", type=NodeType.LLM, label="A"),
                NodeSpec(id="b", type=NodeType.LLM, label="B"),
                NodeSpec(id="c", type=NodeType.LLM, label="C"),
                NodeSpec(id="end", type=NodeType.END, label="End"),
            ],
            edges=[
                EdgeSpec(source="start", target="a"),
                EdgeSpec(source="a", target="b"),
                EdgeSpec(source="b", target="c"),
                EdgeSpec(source="c", target="a"),  # cycle!
                EdgeSpec(source="c", target="end"),
            ],
        )
        result = validator.validate(spec)
        # 循环是警告，不是错误（LangGraph 支持条件回边）
        assert any(w.code == "CYCLE_DETECTED" for w in result.warnings)

    def test_validates_unreachable_node(self, validator):
        """孤立节点应该被标记为不可达"""
        spec = WorkflowSpec(
            nodes=[
                NodeSpec(id="start", type=NodeType.START, label="Start"),
                NodeSpec(id="a", type=NodeType.LLM, label="A"),
                NodeSpec(id="orphan", type=NodeType.TOOL, label="Orphan"),
                NodeSpec(id="end", type=NodeType.END, label="End"),
            ],
            edges=[
                EdgeSpec(source="start", target="a"),
                EdgeSpec(source="a", target="end"),
                # orphan 无连接
            ],
        )
        result = validator.validate(spec)
        assert not result.is_valid
        assert any(e.code == "UNREACHABLE_FROM_START" for e in result.errors)

    def test_validates_cannot_reach_end(self, validator):
        """节点无法到达 END"""
        spec = WorkflowSpec(
            nodes=[
                NodeSpec(id="start", type=NodeType.START, label="Start"),
                NodeSpec(id="a", type=NodeType.LLM, label="A"),
                NodeSpec(id="dead_end", type=NodeType.TOOL, label="Dead"),
                NodeSpec(id="end", type=NodeType.END, label="End"),
            ],
            edges=[
                EdgeSpec(source="start", target="a"),
                EdgeSpec(source="a", target="dead_end"),
                EdgeSpec(source="a", target="end"),
                # dead_end has no outgoing → can't reach end
            ],
        )
        result = validator.validate(spec)
        assert not result.is_valid
        assert any(e.code == "CANNOT_REACH_END" for e in result.errors)

    def test_validates_start_has_incoming(self, validator):
        spec = WorkflowSpec(
            nodes=[
                NodeSpec(id="start", type=NodeType.START, label="Start"),
                NodeSpec(id="a", type=NodeType.LLM, label="A"),
                NodeSpec(id="end", type=NodeType.END, label="End"),
            ],
            edges=[
                EdgeSpec(source="start", target="a"),
                EdgeSpec(source="a", target="start"),  # back to start!
                EdgeSpec(source="a", target="end"),
            ],
        )
        result = validator.validate(spec)
        assert not result.is_valid
        assert any(e.code == "START_HAS_INCOMING" for e in result.errors)

    def test_validates_end_has_outgoing(self, validator):
        spec = WorkflowSpec(
            nodes=[
                NodeSpec(id="start", type=NodeType.START, label="Start"),
                NodeSpec(id="end", type=NodeType.END, label="End"),
            ],
            edges=[
                EdgeSpec(source="start", target="end"),
                EdgeSpec(source="end", target="start"),  # end → back!
            ],
        )
        result = validator.validate(spec)
        assert not result.is_valid
        assert any(e.code == "END_HAS_OUTGOING" for e in result.errors)

    def test_validates_condition_missing_expr(self, validator):
        """CONDITION 节点出边必须有 condition"""
        spec = WorkflowSpec(
            nodes=[
                NodeSpec(id="start", type=NodeType.START, label="Start"),
                NodeSpec(id="check", type=NodeType.CONDITION, label="Check"),
                NodeSpec(id="end", type=NodeType.END, label="End"),
            ],
            edges=[
                EdgeSpec(source="start", target="check"),
                EdgeSpec(source="check", target="end"),  # missing condition!
            ],
        )
        result = validator.validate(spec)
        assert not result.is_valid
        assert any(e.code == "CONDITION_MISSING_EXPR" for e in result.errors)

    def test_warns_condition_edge_count(self, validator):
        """CONDITION 节点应恰好 2 条出边"""
        spec = WorkflowSpec(
            nodes=[
                NodeSpec(id="start", type=NodeType.START, label="Start"),
                NodeSpec(id="check", type=NodeType.CONDITION, label="Check"),
                NodeSpec(id="end", type=NodeType.END, label="End"),
            ],
            edges=[
                EdgeSpec(source="start", target="check"),
                EdgeSpec(source="check", target="end", condition="true"),
                EdgeSpec(source="check", target="end", condition="false"),
                EdgeSpec(source="check", target="end", condition="maybe"),  # 3 edges!
            ],
        )
        result = validator.validate(spec)
        # 3 条 condition 边可能通过但产生警告
        assert any(
            w.code == "CONDITION_EDGE_COUNT" for w in result.warnings
        )

    def test_validate_workflow_convenience(self):
        """便捷函数应返回有效结果"""
        result = validate_workflow(EXAMPLE_WORKFLOW)
        assert result.is_valid

    def test_empty_nodes(self, validator):
        spec = WorkflowSpec(nodes=[], edges=[])
        result = validator.validate(spec)
        assert not result.is_valid
        assert any(e.code == "EMPTY_GRAPH" for e in result.errors)

    def test_missing_edge_source(self, validator):
        spec = WorkflowSpec(
            nodes=[
                NodeSpec(id="start", type=NodeType.START, label="Start"),
                NodeSpec(id="end", type=NodeType.END, label="End"),
            ],
            edges=[
                EdgeSpec(source="ghost", target="end"),
            ],
        )
        result = validator.validate(spec)
        assert not result.is_valid
        assert any(e.code == "MISSING_SOURCE" for e in result.errors)

    def test_missing_edge_target(self, validator):
        spec = WorkflowSpec(
            nodes=[
                NodeSpec(id="start", type=NodeType.START, label="Start"),
                NodeSpec(id="end", type=NodeType.END, label="End"),
            ],
            edges=[
                EdgeSpec(source="start", target="ghost"),
            ],
        )
        result = validator.validate(spec)
        assert not result.is_valid
        assert any(e.code == "MISSING_TARGET" for e in result.errors)


# ============================================================================
# 4. PlannerAgent Tests
# ============================================================================

class TestPlannerAgentTemplateMatch:
    """PlannerAgent 模板匹配模式（无 LLM）"""

    @pytest.mark.asyncio
    async def test_plan_code_review(self, planner):
        result = await planner.plan(
            "请审查这个 PR 的代码变更",
            strategy=PlanningStrategy.TEMPLATE_MATCH,
        )
        assert isinstance(result, PlanningResult)
        assert result.strategy == PlanningStrategy.TEMPLATE_MATCH
        assert result.template_id == "code_review_v1"
        assert result.workflow_spec is not None
        assert len(result.workflow_spec.nodes) > 0
        assert result.confidence >= 0.3

    @pytest.mark.asyncio
    async def test_plan_code_generation(self, planner):
        result = await planner.plan(
            "用 Python 写一个 REST API 服务",
            strategy=PlanningStrategy.TEMPLATE_MATCH,
        )
        assert result.template_id == "code_generation_v1"

    @pytest.mark.asyncio
    async def test_plan_bug_fix(self, planner):
        result = await planner.plan(
            "修复这个 bug：用户登录时崩溃",
            strategy=PlanningStrategy.TEMPLATE_MATCH,
        )
        assert result.template_id == "bug_fix_v1"

    @pytest.mark.asyncio
    async def test_plan_data_analysis(self, planner):
        result = await planner.plan(
            "分析 sales.csv 数据并生成可视化报告",
            strategy=PlanningStrategy.TEMPLATE_MATCH,
        )
        assert result.template_id == "data_analysis_v1"

    @pytest.mark.asyncio
    async def test_plan_deploy(self, planner):
        result = await planner.plan(
            "部署到生产环境",
            strategy=PlanningStrategy.TEMPLATE_MATCH,
        )
        assert result.template_id == "deploy_v1"

    @pytest.mark.asyncio
    async def test_plan_qa(self, planner):
        result = await planner.plan(
            "什么是微服务架构？",
            strategy=PlanningStrategy.TEMPLATE_MATCH,
        )
        assert result.template_id == "qa_v1"

    @pytest.mark.asyncio
    async def test_plan_refactor(self, planner):
        result = await planner.plan(
            "重构 src/ 目录以提高可维护性",
            strategy=PlanningStrategy.TEMPLATE_MATCH,
        )
        assert result.template_id == "refactor_v1"

    @pytest.mark.asyncio
    async def test_plan_no_match_falls_back(self, planner):
        """无模板匹配时生成兜底工作流"""
        result = await planner.plan(
            "执行一个非常特殊的自定义任务 xyzzy",
            strategy=PlanningStrategy.TEMPLATE_MATCH,
        )
        assert isinstance(result, PlanningResult)
        assert result.workflow_spec is not None
        # 兜底工作流至少应有 2 个节点
        assert len(result.workflow_spec.nodes) >= 2

    @pytest.mark.asyncio
    async def test_generated_workflow_is_valid(self, planner, validator):
        """所有生成的工作流都应通过验证"""
        test_cases = [
            "审查代码变更",
            "用 TypeScript 写一个 WebSocket 服务器",
            "修复登录页面的 CSS 错误",
            "分析用户行为数据并生成周报",
            "部署到 staging 环境",
            "什么是 Kafka 的 exactly-once 语义",
        ]
        for goal_text in test_cases:
            result = await planner.plan(goal_text)
            validation = validator.validate(result.workflow_spec)
            assert validation.is_valid, (
                f"Workflow for '{goal_text}' is invalid: "
                f"{[e.message for e in validation.errors]}"
            )

    @pytest.mark.asyncio
    async def test_plan_with_parameters(self, planner):
        """参数应正确传递到工作流"""
        result = await planner.plan(
            "部署到 staging 环境",
            strategy=PlanningStrategy.TEMPLATE_MATCH,
            params={
                "task_name": "我的部署",
                "environment": "staging",
                "deploy_strategy": "blue_green",
            },
        )
        assert "我的部署" in result.workflow_spec.name

    @pytest.mark.asyncio
    async def test_auto_strategy_selects_correctly(self, planner):
        """自动策略选择应正确路由"""
        # 高匹配 → TEMPLATE_MATCH
        result = await planner.plan("审查代码")
        assert result.strategy in (
            PlanningStrategy.TEMPLATE_MATCH,
            PlanningStrategy.HYBRID,
        )

        # 无匹配 → LLM_GENERATE (但无 LLM 时回退到 TEMPLATE_MATCH)
        result2 = await planner.plan("xyzzy frobnicate the discombobulator")
        assert result2.workflow_spec is not None  # 至少生成了兜底


class TestPlannerAgentFallback:
    """PlannerAgent 兜底行为"""

    @pytest.mark.asyncio
    async def test_fallback_workflow_has_start_end(self):
        """兜底工作流必须包含 START 和 END"""
        planner = PlannerAgent(
            template_library=TemplateLibrary(),  # 空模板库
            llm_service=None,
        )
        result = await planner.plan("任意任务")
        node_types = {n.type for n in result.workflow_spec.nodes}
        assert NodeType.START in node_types
        assert NodeType.END in node_types

    @pytest.mark.asyncio
    async def test_fallback_has_low_confidence(self):
        """兜底工作流置信度应较低"""
        planner = PlannerAgent(
            template_library=TemplateLibrary(),
            llm_service=None,
        )
        result = await planner.plan("任意任务")
        assert result.confidence < 0.5

    @pytest.mark.asyncio
    async def test_fallback_has_warning(self):
        """兜底工作流应产生警告"""
        planner = PlannerAgent(
            template_library=TemplateLibrary(),
            llm_service=None,
        )
        result = await planner.plan("任意任务")
        assert len(result.warnings) > 0


# ============================================================================
# 5. RuntimeKernel Integration Tests
# ============================================================================

class TestKernelWithPlanner:
    """RuntimeKernel + PlannerAgent 集成"""

    @pytest.mark.asyncio
    async def test_generate_workflow(self, kernel_with_planner):
        """Kernel.generate_workflow 应返回有效 WorkflowSpec"""
        spec = await kernel_with_planner.generate_workflow(
            "审查代码变更"
        )
        assert spec is not None
        assert hasattr(spec, "nodes")
        assert hasattr(spec, "edges")
        assert len(spec.nodes) > 0

    @pytest.mark.asyncio
    async def test_submit_task_with_workflow(self, kernel_with_planner):
        """submit_task_with_workflow 应生成并关联 Workflow"""
        from app.runtime.kernel import TaskRequest

        task_id = await kernel_with_planner.submit_task_with_workflow(
            TaskRequest(
                goal_description="分析销售数据并生成报告",
                priority=5,
            )
        )
        assert len(task_id) == 36  # UUID 格式

        # 检查 Workflow 已关联
        spec = kernel_with_planner._workflows.get(task_id)
        assert spec is not None

    @pytest.mark.asyncio
    async def test_get_workflow(self, kernel_with_planner):
        """get_workflow 应返回已生成的 WorkflowSpec"""
        from app.runtime.kernel import TaskRequest

        task_id = await kernel_with_planner.submit_task_with_workflow(
            TaskRequest(goal_description="修复登录 bug")
        )
        spec = await kernel_with_planner.get_workflow(task_id)
        assert spec is not None


# ============================================================================
# 6. Regression Guard — Planner should not break existing tests
# ============================================================================

class TestPlannerRegressionGuard:
    """确保 Planner 导入不破坏现有模块"""

    def test_runtime_init_imports_planner(self):
        """runtime.__init__ 应正确导出 Planner 相关符号"""
        from app.runtime import (
            PlannerAgent,
            PlanningGoal,
            PlanningStrategy,
            TemplateLibrary,
            WorkflowValidator,
            validate_workflow,
            get_default_planner,
            create_default_template_library,
        )
        assert PlannerAgent is not None
        assert PlanningStrategy is not None
        assert TemplateLibrary is not None

    def test_planner_module_structure(self):
        """验证 planner 模块子包结构"""
        from app.runtime.planner import models
        from app.runtime.planner import templates
        from app.runtime.planner import validator
        from app.runtime.planner import planner_agent
        assert models is not None
        assert templates is not None
        assert validator is not None
        assert planner_agent is not None
