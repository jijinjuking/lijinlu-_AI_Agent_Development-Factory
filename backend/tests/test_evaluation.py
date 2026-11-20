"""
W18 Self Evaluation — 完整测试套件

覆盖：
  1. 数据模型（DimensionScore / Issue / EvaluationResult / EvaluationContext / EvaluatorConfig）
  2. 评分引擎（Scorer — 8 个维度）
  3. 主评估器（SelfEvaluator — evaluate / evaluate_node / evaluate_step / evaluate_quick）
  4. 幻觉检测（HallucinationDetector — 5 种策略）
  5. 代码质量（CodeQualityChecker — 语法/行长度/结构/注释/异常处理）
  6. 工具指标（ToolMetricsCollector — 记录/聚合/导出）
  7. API 端点（5 个路由）
  8. 数据库持久化（EvaluationRecord CRUD）
"""

import pytest
import pytest_asyncio
import uuid
from httpx import AsyncClient, ASGITransport


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def evaluation_context():
    """构造标准评估上下文"""
    from app.runtime.evaluation.models import EvaluationContext
    return EvaluationContext(
        task_id=str(uuid.uuid4()),
        node_id="node-001",
        agent_name="test_agent",
        goal_description="分析用户数据并生成可视化报告",
        output_text="已生成 3 个可视化图表: 柱状图、折线图、饼图。数据覆盖率达到 95%。",
        output_data={"charts": ["bar", "line", "pie"], "coverage": 0.95},
        tokens_used=5000,
        tokens_input=3000,
        tokens_output=2000,
        tool_calls_total=5,
        tool_calls_success=4,
        error_count=1,
        recovery_count=1,
        execution_time_ms=2500.0,
        context_window_used=40000,
        context_window_max=128000,
        code_output="def hello():\n    print('hello world')\n    return True",
        code_language="python",
    )


@pytest.fixture
def evaluator_config():
    """构造评估器配置"""
    from app.runtime.evaluation.models import EvaluatorConfig
    return EvaluatorConfig()


@pytest.fixture
def self_evaluator(evaluator_config):
    """构造 SelfEvaluator 实例"""
    from app.runtime.evaluation import SelfEvaluator
    return SelfEvaluator(evaluator_config)


# ============================================================================
# 1. 数据模型测试
# ============================================================================


class TestDataModels:
    """测试评估数据模型"""

    def test_dimension_score_creation(self):
        from app.runtime.evaluation.models import DimensionScore, EvaluationMetric
        ds = DimensionScore(
            metric=EvaluationMetric.TASK_SUCCESS,
            score=0.85,
            reason="测试评分",
        )
        assert ds.passed is True
        assert ds.score == 0.85
        assert ds.metric == EvaluationMetric.TASK_SUCCESS

    def test_dimension_score_failed(self):
        from app.runtime.evaluation.models import DimensionScore, EvaluationMetric
        ds = DimensionScore(
            metric=EvaluationMetric.HALLUCINATION,
            score=0.3,
            threshold=0.5,
        )
        assert ds.passed is False

    def test_dimension_score_to_dict(self):
        from app.runtime.evaluation.models import DimensionScore, EvaluationMetric
        ds = DimensionScore(metric=EvaluationMetric.COST_EFFICIENCY, score=0.7)
        d = ds.to_dict()
        assert d["metric"] == "cost_efficiency"
        assert d["score"] == 0.7
        assert "passed" in d
        assert "reason" in d

    def test_issue_creation(self):
        from app.runtime.evaluation.models import Issue, EvaluationMetric, Severity
        issue = Issue(
            code="TEST_ISSUE",
            severity=Severity.MAJOR,
            message="测试问题",
            metric=EvaluationMetric.TASK_SUCCESS,
            suggestion="改进建议",
        )
        d = issue.to_dict()
        assert d["code"] == "TEST_ISSUE"
        assert d["severity"] == "major"
        assert d["message"] == "测试问题"

    def test_evaluation_result_to_dict(self):
        from app.runtime.evaluation.models import EvaluationResult, EvaluationScope
        result = EvaluationResult(
            task_id="task-1",
            scope=EvaluationScope.TASK,
            overall_score=0.85,
            passed=True,
            dimension_scores=[],
            suggestions=["改进点 1", "改进点 2"],
        )
        d = result.to_dict()
        assert d["task_id"] == "task-1"
        assert d["overall_score"] == 0.85
        assert len(d["suggestions"]) == 2

    def test_evaluation_result_critical_issues(self):
        from app.runtime.evaluation.models import (
            EvaluationResult, Issue, EvaluationMetric, Severity,
        )
        issues = [
            Issue(code="C1", severity=Severity.CRITICAL, message="严重问题", metric=EvaluationMetric.TASK_SUCCESS),
            Issue(code="M1", severity=Severity.MAJOR, message="重要问题", metric=EvaluationMetric.TOOL_SUCCESS_RATE),
            Issue(code="I1", severity=Severity.INFO, message="提示", metric=EvaluationMetric.CONTEXT_EFFICIENCY),
        ]
        # 直接用 EvaluationResult 构造器
        result = EvaluationResult(task_id="t1")
        result.issues = issues
        assert len(result.critical_issues) == 1
        assert len(result.major_issues) == 1

    def test_evaluation_context_tool_success_rate(self, evaluation_context):
        assert evaluation_context.tool_success_rate == 0.8

    def test_evaluation_context_context_utilization(self, evaluation_context):
        assert evaluation_context.context_utilization == pytest.approx(40000 / 128000, rel=0.01)

    def test_evaluator_config_defaults(self, evaluator_config):
        from app.runtime.evaluation.models import EvaluationMetric
        assert evaluator_config.global_threshold == 0.7
        assert evaluator_config.get_weight(EvaluationMetric.TASK_SUCCESS) == 0.25
        assert evaluator_config.get_threshold(EvaluationMetric.HALLUCINATION) == 0.5


# ============================================================================
# 2. 评分引擎测试
# ============================================================================


class TestScorer:
    """测试评分器各维度评分逻辑"""

    def test_compute_weighted_score(self):
        from app.runtime.evaluation.models import DimensionScore, EvaluationMetric
        from app.runtime.evaluation.scoring import compute_weighted_score
        ds_list = [
            DimensionScore(metric=EvaluationMetric.TASK_SUCCESS, score=0.9, weight=0.5),
            DimensionScore(metric=EvaluationMetric.OUTPUT_RELEVANCE, score=0.7, weight=0.5),
        ]
        score, passed = compute_weighted_score(ds_list, 0.7)
        assert score == pytest.approx(0.8, rel=0.01)
        assert passed is True

    def test_compute_weighted_score_below_threshold(self):
        from app.runtime.evaluation.models import DimensionScore, EvaluationMetric
        from app.runtime.evaluation.scoring import compute_weighted_score
        ds_list = [
            DimensionScore(metric=EvaluationMetric.TASK_SUCCESS, score=0.3, weight=0.5),
            DimensionScore(metric=EvaluationMetric.OUTPUT_RELEVANCE, score=0.4, weight=0.5),
        ]
        score, passed = compute_weighted_score(ds_list, 0.7)
        assert passed is False

    def test_evaluate_task_success(self, evaluator_config, evaluation_context):
        from app.runtime.evaluation.scoring import Scorer
        scorer = Scorer(evaluator_config)
        ds = scorer.evaluate_task_success(evaluation_context)
        assert 0.0 <= ds.score <= 1.0

    def test_evaluate_output_relevance(self, evaluator_config, evaluation_context):
        from app.runtime.evaluation.scoring import Scorer
        scorer = Scorer(evaluator_config)
        ds = scorer.evaluate_output_relevance(evaluation_context)
        assert 0.0 <= ds.score <= 1.0

    def test_evaluate_tool_success_rate(self, evaluator_config, evaluation_context):
        from app.runtime.evaluation.scoring import Scorer
        scorer = Scorer(evaluator_config)
        ds = scorer.evaluate_tool_success_rate(evaluation_context)
        assert ds.score == 0.8

    def test_evaluate_cost_efficiency(self, evaluator_config, evaluation_context):
        from app.runtime.evaluation.scoring import Scorer
        scorer = Scorer(evaluator_config)
        ds = scorer.evaluate_cost_efficiency(evaluation_context)
        assert 0.0 <= ds.score <= 1.0

    def test_evaluate_context_efficiency(self, evaluator_config, evaluation_context):
        from app.runtime.evaluation.scoring import Scorer
        scorer = Scorer(evaluator_config)
        ds = scorer.evaluate_context_efficiency(evaluation_context)
        assert ds.score == 1.0  # 40K/128K = 31.25% → 最佳区间

    def test_evaluate_runtime_stability(self, evaluator_config, evaluation_context):
        from app.runtime.evaluation.scoring import Scorer
        scorer = Scorer(evaluator_config)
        ds = scorer.evaluate_runtime_stability(evaluation_context)
        assert ds.score == 0.8  # 有错误但全部恢复

    @pytest.mark.asyncio
    async def test_scorer_unified_evaluate(self, evaluator_config, evaluation_context):
        from app.runtime.evaluation.scoring import Scorer
        from app.runtime.evaluation.models import EvaluationMetric
        scorer = Scorer(evaluator_config)

        for metric in EvaluationMetric:
            ds = await scorer.evaluate(metric, evaluation_context)  # async dispatch
            assert ds is not None
            assert 0.0 <= ds.score <= 1.0

    def test_score_method(self, evaluator_config, evaluation_context):
        from app.runtime.evaluation.scoring import Scorer
        from app.runtime.evaluation.models import EvaluationMetric, DimensionScore
        scorer = Scorer(evaluator_config)
        ds_list = [
            scorer.evaluate_task_success(evaluation_context),
            scorer.evaluate_output_relevance(evaluation_context),
        ]
        result = scorer.score("task-1", ds_list)
        assert result.task_id == "task-1"
        assert 0.0 <= result.overall_score <= 1.0


# ============================================================================
# 3. 主评估器测试
# ============================================================================


class TestSelfEvaluator:
    """测试 SelfEvaluator 完整评估流程"""

    @pytest.mark.asyncio
    async def test_evaluate_complete(self, self_evaluator, evaluation_context):
        from app.runtime.evaluation.models import EvaluationScope
        result = await self_evaluator.evaluate(
            "task-1",
            evaluation_context,
            scope=EvaluationScope.TASK,
            agent_name="test_agent",
        )
        assert result.task_id == "task-1"
        assert 0.0 <= result.overall_score <= 1.0
        assert len(result.dimension_scores) > 0
        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_evaluate_node(self, self_evaluator, evaluation_context):
        result = await self_evaluator.evaluate_node(
            "task-1", "node-001", evaluation_context, agent_name="test_agent",
        )
        assert result.scope.value == "node"
        assert result.node_id == "node-001"

    @pytest.mark.asyncio
    async def test_evaluate_step(self, self_evaluator, evaluation_context):
        result = await self_evaluator.evaluate_step(
            "task-1", "step-001", evaluation_context, agent_name="test_agent",
        )
        assert result.scope.value == "step"

    def test_evaluate_quick(self, self_evaluator, evaluation_context):
        result = self_evaluator.evaluate_quick("task-1", evaluation_context)
        assert result is not None
        assert 0.0 <= result.overall_score <= 1.0

    def test_record_tool_call(self, self_evaluator):
        from app.runtime.evaluation.tool_metrics import ToolCallRecord
        record = ToolCallRecord(
            tool_name="git_commit",
            task_id="task-1",
            success=True,
            execution_time_ms=50.0,
        )
        self_evaluator.record_tool_call(record)
        summary = self_evaluator.get_tool_summary()
        assert summary["total"] >= 1

    @pytest.mark.asyncio
    async def test_evaluate_empty_output(self, self_evaluator):
        from app.runtime.evaluation.models import EvaluationContext, EvaluationScope
        ctx = EvaluationContext(task_id="task-1", output_text="")
        result = await self_evaluator.evaluate("task-1", ctx, scope=EvaluationScope.TASK)
        assert result.overall_score > 0  # 空输出不给 0 分（幻觉检测给满分）


# ============================================================================
# 4. 幻觉检测测试
# ============================================================================


class TestHallucinationDetector:
    """测试幻觉检测器"""

    def test_detect_fake_paths(self, evaluator_config):
        from app.runtime.evaluation.hallucination import HallucinationDetector
        detector = HallucinationDetector(evaluator_config)
        issues = detector.detect_text("请查看文件 /fake/path/to/file.py 的内容")
        assert len(issues) > 0
        assert any("虚构路径" in i.message for i in issues)

    def test_detect_absurd_numbers(self, evaluator_config):
        from app.runtime.evaluation.hallucination import HallucinationDetector
        detector = HallucinationDetector(evaluator_config)
        # 格式对齐 regex: "\d{3,}\s*%\s*(成功率|准确率)"
        issues = detector.detect_text("完成率: 500% 成功率")
        assert len(issues) > 0
        assert any("离谱数据" in i.message for i in issues)

    def test_detect_contradictions(self, evaluator_config):
        from app.runtime.evaluation.hallucination import HallucinationDetector
        config = evaluator_config
        config.hallucination_strictness = "medium"
        detector = HallucinationDetector(config)
        issues = detector.detect_text("这个函数没有问题，但是有bug需要修复")
        assert len(issues) > 0
        assert any("矛盾" in i.message for i in issues)

    def test_detect_overconfidence(self, evaluator_config):
        from app.runtime.evaluation.hallucination import HallucinationDetector
        config = evaluator_config
        config.hallucination_strictness = "medium"
        detector = HallucinationDetector(config)
        issues = detector.detect_text("这个方案绝对正确，100%无误")
        assert len(issues) > 0

    def test_detect_fake_apis(self, evaluator_config):
        from app.runtime.evaluation.hallucination import HallucinationDetector
        config = evaluator_config
        config.hallucination_strictness = "high"
        detector = HallucinationDetector(config)
        # 格式对齐 regex: "\b(fake|dummy|mock)_(library|api|...)\b"
        issues = detector.detect_text("请使用 fake_library 来获取数据")
        assert len(issues) > 0

    def test_check_false_versions(self, evaluator_config):
        from app.runtime.evaluation.hallucination import HallucinationDetector
        detector = HallucinationDetector(evaluator_config)
        issues = detector.detect_text("Python 2.5 引入了 asyncio 库")
        assert any("版本声明错误" in i.message for i in issues)

    def test_detect_unsupported_apis(self, evaluator_config):
        from app.runtime.evaluation.hallucination import HallucinationDetector
        detector = HallucinationDetector(evaluator_config)
        issues = detector.detect(
            "调用 unsupported_method  获取结果",
            unsupported_apis=["unsupported_method"],
        )
        assert any("不支持的 API" in i.message for i in issues)

    def test_clean_output_no_issues(self, evaluator_config):
        from app.runtime.evaluation.hallucination import HallucinationDetector
        detector = HallucinationDetector(evaluator_config)
        issues = detector.detect_text("任务已成功完成，生成了相应的报告文件。")
        assert len(issues) == 0

    def test_evaluate_method(self, evaluator_config, evaluation_context):
        from app.runtime.evaluation.hallucination import HallucinationDetector
        detector = HallucinationDetector(evaluator_config)
        ds = detector.evaluate(evaluation_context)
        assert ds is not None
        assert 0.0 <= ds.score <= 1.0

    def test_evaluate_empty_text(self, evaluator_config):
        from app.runtime.evaluation.hallucination import HallucinationDetector
        from app.runtime.evaluation.models import EvaluationContext
        detector = HallucinationDetector(evaluator_config)
        ctx = EvaluationContext(task_id="t1", output_text="")
        ds = detector.evaluate(ctx)
        assert ds.score == 1.0  # 空文本给满分


# ============================================================================
# 5. 代码质量测试
# ============================================================================


class TestCodeQualityChecker:
    """测试代码质量检测器"""

    def test_check_valid_python(self, evaluator_config):
        from app.runtime.evaluation.code_quality import CodeQualityChecker
        checker = CodeQualityChecker(evaluator_config)
        result = checker.check("def hello():\n    return 'world'")
        assert result["syntax_valid"] is True

    def test_check_syntax_error(self, evaluator_config):
        from app.runtime.evaluation.code_quality import CodeQualityChecker
        checker = CodeQualityChecker(evaluator_config)
        result = checker.check("def hello(\n    return 'world'")
        assert result["syntax_valid"] is False

    def test_check_empty_code(self, evaluator_config):
        from app.runtime.evaluation.code_quality import CodeQualityChecker
        checker = CodeQualityChecker(evaluator_config)
        result = checker.check("")
        assert result["syntax_valid"] is False

    def test_check_comments_ratio(self, evaluator_config):
        from app.runtime.evaluation.code_quality import CodeQualityChecker
        checker = CodeQualityChecker(evaluator_config)
        result = checker.check("# comment\nx = 1\n")
        assert "comment_ratio" in result["quality_metrics"]

    def test_evaluate_with_code(self, evaluator_config, evaluation_context):
        from app.runtime.evaluation.code_quality import CodeQualityChecker
        checker = CodeQualityChecker(evaluator_config)
        ds = checker.evaluate(evaluation_context)
        assert ds is not None
        assert 0.0 <= ds.score <= 1.0

    def test_evaluate_no_code(self, evaluator_config):
        from app.runtime.evaluation.code_quality import CodeQualityChecker
        from app.runtime.evaluation.models import EvaluationContext
        checker = CodeQualityChecker(evaluator_config)
        ctx = EvaluationContext(task_id="t1", output_text="纯文本无代码")
        ds = checker.evaluate(ctx)
        assert ds.score == 0.8  # 无代码不扣分

    def test_looks_like_python(self, evaluator_config):
        from app.runtime.evaluation.code_quality import CodeQualityChecker
        checker = CodeQualityChecker(evaluator_config)
        assert checker._looks_like_python("def func(): pass") is True
        assert checker._looks_like_python("import os") is True
        assert checker._looks_like_python("plain text") is False


# ============================================================================
# 6. 工具指标测试
# ============================================================================


class TestToolMetricsCollector:
    """测试工具指标收集器"""

    def test_record_and_get_metrics(self):
        from app.runtime.evaluation.tool_metrics import ToolMetricsCollector, ToolCallRecord
        collector = ToolMetricsCollector()
        collector.record(ToolCallRecord(
            tool_name="git_commit", task_id="t1", success=True, execution_time_ms=100.0,
        ))
        collector.record(ToolCallRecord(
            tool_name="git_commit", task_id="t1", success=False, execution_time_ms=200.0,
        ))
        metrics = collector.get_metrics("git_commit")
        assert metrics is not None
        assert metrics.total_calls == 2
        assert metrics.success_rate == 0.5
        assert metrics.avg_time_ms == 150.0

    def test_record_by_name(self):
        from app.runtime.evaluation.tool_metrics import ToolMetricsCollector
        collector = ToolMetricsCollector()
        collector.record("file_read", success=True, execution_time_ms=30.0)
        metrics = collector.get_metrics("file_read")
        assert metrics.total_calls == 1
        assert metrics.success_rate == 1.0

    def test_get_summary(self):
        from app.runtime.evaluation.tool_metrics import ToolMetricsCollector, ToolCallRecord
        collector = ToolMetricsCollector()
        collector.record(ToolCallRecord(tool_name="t1", task_id="x", success=True, execution_time_ms=10))
        collector.record(ToolCallRecord(tool_name="t2", task_id="x", success=False, execution_time_ms=20))
        summary = collector.get_summary()
        assert summary["total"] == 2
        assert summary["success"] == 1
        assert summary["success_rate"] == 0.5

    def test_export_import(self):
        from app.runtime.evaluation.tool_metrics import ToolMetricsCollector, ToolCallRecord
        collector = ToolMetricsCollector()
        collector.record(ToolCallRecord(tool_name="t1", task_id="x"))
        data = collector.export_data()
        assert len(data) == 1

        collector2 = ToolMetricsCollector()
        collector2.import_data(data)
        assert len(collector2.get_records()) == 1

    def test_get_task_records(self):
        from app.runtime.evaluation.tool_metrics import ToolMetricsCollector, ToolCallRecord
        collector = ToolMetricsCollector()
        collector.record(ToolCallRecord(tool_name="t1", task_id="task-a"))
        collector.record(ToolCallRecord(tool_name="t2", task_id="task-b"))
        records = collector.get_task_records("task-a")
        assert len(records) == 1
        assert records[0].tool_name == "t1"

    def test_reset(self):
        from app.runtime.evaluation.tool_metrics import ToolMetricsCollector, ToolCallRecord
        collector = ToolMetricsCollector()
        collector.record(ToolCallRecord(tool_name="t1", task_id="x"))
        collector.reset()
        assert len(collector.get_records()) == 0

    def test_get_total_metrics(self):
        from app.runtime.evaluation.tool_metrics import ToolMetricsCollector, ToolCallRecord
        collector = ToolMetricsCollector()
        collector.record(ToolCallRecord(tool_name="t1", task_id="x", success=True, execution_time_ms=10))
        collector.record(ToolCallRecord(tool_name="t2", task_id="x", success=True, execution_time_ms=20))
        total = collector.get_total_metrics()
        assert total.total_calls == 2


# ============================================================================
# 7. API 端点集成测试
# ============================================================================


@pytest_asyncio.fixture
async def evaluation_client(test_engine):
    """创建 AsyncClient 用于评估 API 测试"""
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestEvaluationAPI:
    """测试评估 API 端点"""

    @pytest.mark.asyncio
    async def test_trigger_evaluation_creates_record(self, evaluation_client):
        """POST /evaluation/evaluate → 创建评估记录"""
        payload = {
            "task_id": str(uuid.uuid4()),
            "scope": "task",
            "agent_name": "test_agent",
            "context": {
                "task_id": str(uuid.uuid4()),
                "goal_description": "测试任务",
                "output_text": "任务已成功完成，生成了测试报告",
                "tokens_used": 1000,
                "tokens_input": 600,
                "tokens_output": 400,
                "tool_calls_total": 3,
                "tool_calls_success": 3,
                "error_count": 0,
                "recovery_count": 0,
                "execution_time_ms": 1500.0,
            },
        }
        response = await evaluation_client.post("/api/v1/evaluation/evaluate", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["task_id"] == payload["task_id"]
        assert "overall_score" in data
        assert "dimension_scores" in data
        assert data["agent_name"] == "test_agent"

    @pytest.mark.asyncio
    async def test_list_evaluation_records(self, evaluation_client):
        """GET /evaluation/records → 列出评估记录"""
        response = await evaluation_client.get("/api/v1/evaluation/records")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_evaluation_record_not_found(self, evaluation_client):
        """GET /evaluation/records/{id} → 不存在的记录返回 404"""
        fake_id = str(uuid.uuid4())
        response = await evaluation_client.get(f"/api/v1/evaluation/records/{fake_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_task_evaluations_empty(self, evaluation_client):
        """GET /evaluation/task/{task_id} → 空结果"""
        response = await evaluation_client.get(f"/api/v1/evaluation/task/{str(uuid.uuid4())}")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_evaluation_stats(self, evaluation_client):
        """GET /evaluation/stats → 评估统计"""
        response = await evaluation_client.get("/api/v1/evaluation/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_evaluations" in data
        assert "average_score" in data

    @pytest.mark.asyncio
    async def test_filter_by_passed(self, evaluation_client):
        """GET /evaluation/records?passed=true → 按通过状态筛选"""
        response = await evaluation_client.get("/api/v1/evaluation/records?passed=true")
        assert response.status_code == 200
        data = response.json()
        for record in data:
            assert record["passed"] is True

    @pytest.mark.asyncio
    async def test_delete_evaluation_record(self, evaluation_client):
        """DELETE /evaluation/records/{id} → 删除评估记录"""
        # 先创建一个记录
        payload = {
            "task_id": str(uuid.uuid4()),
            "scope": "task",
            "agent_name": "delete_test",
            "context": {
                "task_id": str(uuid.uuid4()),
                "goal_description": "删除测试",
                "output_text": "测试输出",
                "tokens_used": 100,
            },
        }
        create_resp = await evaluation_client.post("/api/v1/evaluation/evaluate", json=payload)
        record_id = create_resp.json()["id"]

        # 删除
        delete_resp = await evaluation_client.delete(f"/api/v1/evaluation/records/{record_id}")
        assert delete_resp.status_code == 204

        # 确认已删除
        get_resp = await evaluation_client.get(f"/api/v1/evaluation/records/{record_id}")
        assert get_resp.status_code == 404


# ============================================================================
# 8. 数据库模型测试
# ============================================================================


class TestEvaluationRecord:
    """测试 EvaluationRecord ORM 模型"""

    def test_from_evaluation_result(self, self_evaluator, evaluation_context):
        from app.runtime.evaluation.models import EvaluationScope
        from app.models.evaluation import EvaluationRecord
        import asyncio
        result = asyncio.run(self_evaluator.evaluate(
            "task-1", evaluation_context, scope=EvaluationScope.TASK,
        ))
        record = EvaluationRecord.from_evaluation_result(result, task_id="task-1")
        assert record.task_id == "task-1"
        assert record.overall_score == result.overall_score
        assert record.passed == result.passed
        assert record.dimension_scores is not None

    def test_to_dict(self, self_evaluator, evaluation_context):
        from app.runtime.evaluation.models import EvaluationScope
        from app.models.evaluation import EvaluationRecord
        import asyncio
        result = asyncio.run(self_evaluator.evaluate(
            "task-1", evaluation_context, scope=EvaluationScope.TASK,
        ))
        record = EvaluationRecord.from_evaluation_result(result, task_id="task-1")
        d = record.to_dict()
        assert "id" in d
        assert "task_id" in d
        assert "overall_score" in d
        assert "dimension_scores" in d
        assert "issues" in d
