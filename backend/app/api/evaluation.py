"""
W18 Self Evaluation — API 路由

端点：
  GET    /evaluation/records             — 列出评估记录（支持筛选）
  GET    /evaluation/records/{record_id}  — 获取单条记录详情
  GET    /evaluation/task/{task_id}       — 获取指定任务的所有评估
  POST   /evaluation/evaluate             — 手动触发评估
  GET    /evaluation/stats                — 评估统计
  DELETE /evaluation/records/{record_id}  — 删除评估记录
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.evaluation import EvaluationRecord
from app.schemas.evaluation import (
    EvaluationRequest,
    EvaluationResponse,
    EvaluationSummary,
    EvaluationStatsResponse,
    EvaluationTriggerResponse,
)
from app.runtime.evaluation import SelfEvaluator, EvaluatorConfig

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# Helpers
# ============================================================================


def record_to_response(record: EvaluationRecord) -> EvaluationResponse:
    """ORM → Response 转换"""
    return EvaluationResponse(
        id=str(record.id),
        task_id=record.task_id,
        node_id=record.node_id,
        agent_id=record.agent_id,
        agent_name=record.agent_name,
        scope=record.scope,
        overall_score=record.overall_score,
        passed=record.passed,
        threshold=record.threshold,
        dimension_scores=record.dimension_scores or [],
        issues=record.issues or [],
        suggestions=record.suggestions or [],
        execution_time_ms=record.execution_time_ms,
        evaluator_version=record.evaluator_version,
        evaluation_timestamp=record.evaluation_timestamp,
        created_at=record.created_at.isoformat() if record.created_at else "",
        updated_at=record.updated_at.isoformat() if record.updated_at else "",
    )


def record_to_summary(record: EvaluationRecord) -> EvaluationSummary:
    """ORM → Summary 转换"""
    issues = record.issues or []
    critical = sum(1 for i in issues if i.get("severity") == "critical")
    major = sum(1 for i in issues if i.get("severity") == "major")
    return EvaluationSummary(
        task_id=record.task_id,
        agent_name=record.agent_name,
        overall_score=record.overall_score,
        passed=record.passed,
        issue_count=len(issues),
        critical_count=critical,
        major_count=major,
        evaluation_timestamp=record.evaluation_timestamp,
    )


# ============================================================================
# 查询端点
# ============================================================================


@router.get("/records", response_model=list[EvaluationSummary])
async def list_evaluation_records(
    task_id: Optional[str] = Query(default=None, description="按任务 ID 筛选"),
    agent_name: Optional[str] = Query(default=None, description="按 Agent 名称筛选"),
    passed: Optional[bool] = Query(default=None, description="按是否通过筛选"),
    limit: int = Query(default=50, ge=1, le=500, description="返回数量上限"),
    offset: int = Query(default=0, ge=0, description="分页偏移"),
    db: AsyncSession = Depends(get_db),
):
    """列出评估记录，支持按任务/Agent/通过状态筛选。"""
    query = select(EvaluationRecord).order_by(EvaluationRecord.created_at.desc())

    conditions = []
    if task_id:
        conditions.append(EvaluationRecord.task_id == task_id)
    if agent_name:
        conditions.append(EvaluationRecord.agent_name == agent_name)
    if passed is not None:
        conditions.append(EvaluationRecord.passed == passed)

    if conditions:
        query = query.where(and_(*conditions))

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    records = result.scalars().all()
    return [record_to_summary(r) for r in records]


@router.get("/records/{record_id}", response_model=EvaluationResponse)
async def get_evaluation_record(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取单条评估记录详情。"""
    uid = uuid.UUID(record_id)
    result = await db.execute(
        select(EvaluationRecord).where(EvaluationRecord.id == uid)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="评估记录不存在")
    return record_to_response(record)


@router.get("/task/{task_id}", response_model=list[EvaluationSummary])
async def get_task_evaluations(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取指定任务的所有评估记录（按时间排序）。"""
    result = await db.execute(
        select(EvaluationRecord)
        .where(EvaluationRecord.task_id == task_id)
        .order_by(EvaluationRecord.created_at.desc())
    )
    records = result.scalars().all()
    return [record_to_summary(r) for r in records]


# ============================================================================
# 评估统计
# ============================================================================


@router.get("/stats", response_model=EvaluationStatsResponse)
async def get_evaluation_stats(
    db: AsyncSession = Depends(get_db),
):
    """获取全局评估统计数据。"""
    # 总数
    total_result = await db.execute(func.count(EvaluationRecord.id))
    total = total_result.scalar() or 0

    if total == 0:
        return EvaluationStatsResponse()

    # 通过率
    passed_result = await db.execute(
        select(func.count(EvaluationRecord.id)).where(EvaluationRecord.passed == True)
    )
    passed_count = passed_result.scalar() or 0

    # 平均分
    avg_result = await db.execute(func.avg(EvaluationRecord.overall_score))
    avg_score = avg_result.scalar() or 0.0

    # 问题统计
    all_records_result = await db.execute(select(EvaluationRecord))
    records = all_records_result.scalars().all()

    total_issues = 0
    critical_issues = 0
    major_issues = 0
    dimension_scores: dict[str, list[float]] = {}
    score_buckets: dict[str, int] = {"excellent": 0, "good": 0, "fair": 0, "poor": 0}

    for record in records:
        issues = record.issues or []
        total_issues += len(issues)
        critical_issues += sum(1 for i in issues if i.get("severity") == "critical")
        major_issues += sum(1 for i in issues if i.get("severity") == "major")

        # 分数分布
        score = record.overall_score
        if score >= 0.8:
            score_buckets["excellent"] += 1
        elif score >= 0.6:
            score_buckets["good"] += 1
        elif score >= 0.4:
            score_buckets["fair"] += 1
        else:
            score_buckets["poor"] += 1

        # 维度平均分
        for ds in record.dimension_scores or []:
            metric = ds.get("metric", "unknown")
            if metric not in dimension_scores:
                dimension_scores[metric] = []
            dimension_scores[metric].append(ds.get("score", 0))

    dimension_averages = {
        metric: round(sum(scores) / len(scores), 4)
        for metric, scores in dimension_scores.items()
    }

    # 改进领域排序（按平均分最低的维度）
    sorted_dimensions = sorted(dimension_averages.items(), key=lambda x: x[1])
    top_improvement_areas = [f"{metric} (avg: {avg:.2f})" for metric, avg in sorted_dimensions[:5]]

    return EvaluationStatsResponse(
        total_evaluations=total,
        total_tasks_evaluated=len(set(r.task_id for r in records)),
        average_score=round(avg_score, 4),
        pass_rate=round(passed_count / total, 4) if total > 0 else 0.0,
        total_issues_found=total_issues,
        critical_issues_count=critical_issues,
        major_issues_count=major_issues,
        top_improvement_areas=top_improvement_areas,
        score_distribution=score_buckets,
        dimension_averages=dimension_averages,
    )


# ============================================================================
# 手动触发评估
# ============================================================================


@router.post("/evaluate", response_model=EvaluationResponse, status_code=201)
async def trigger_evaluation(
    body: EvaluationRequest,
    db: AsyncSession = Depends(get_db),
):
    """手动触发一次评估。

    流程：
    1. 将请求上下文转为 runtime EvaluationContext
    2. 调用 SelfEvaluator.evaluate()
    3. 持久化结果到 evaluation_records 表
    4. 返回完整评估结果
    """
    try:
        runtime_ctx = body.context.to_runtime_context()
        config = EvaluatorConfig()
        evaluator = SelfEvaluator(config)

        from app.runtime.evaluation.models import EvaluationScope
        scope_map = {
            "task": EvaluationScope.TASK,
            "node": EvaluationScope.NODE,
            "step": EvaluationScope.STEP,
        }
        scope = scope_map.get(body.scope, EvaluationScope.TASK)

        result = await evaluator.evaluate(
            task_id=body.task_id,
            ctx=runtime_ctx,
            scope=scope,
            node_id=body.node_id,
            agent_name=body.agent_name,
        )

        # 持久化
        record = EvaluationRecord.from_evaluation_result(
            result,
            task_id=body.task_id,
            agent_name=body.agent_name,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)

        return record_to_response(record)

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"评估模块加载失败: {e}",
        )
    except Exception as e:
        logger.exception("Evaluation failed for task=%s", body.task_id)
        raise HTTPException(status_code=500, detail=f"评估失败: {e}")


@router.delete("/records/{record_id}", status_code=204)
async def delete_evaluation_record(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除评估记录。"""
    uid = uuid.UUID(record_id)
    result = await db.execute(
        select(EvaluationRecord).where(EvaluationRecord.id == uid)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="评估记录不存在")
    await db.delete(record)
    await db.commit()


# ============================================================================
# Datasets & Cases（暂用内存存储，后续迁移到 DB）
# ============================================================================

@router.get("/datasets")
async def list_datasets():
    """列出评测数据集（暂返回空，后续实现 Dataset 模型）。"""
    return []


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str):
    """获取单个数据集详情（暂返回 404）。"""
    raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")


@router.get("/cases")
async def list_evaluation_cases(
    dataset_id: Optional[str] = Query(default=None),
):
    """列出评测用例（暂返回空，后续实现 Case 模型）。"""
    return []


@router.get("/cases/{case_id}")
async def get_evaluation_case(case_id: str):
    """获取单个评测用例（暂返回 404）。"""
    raise HTTPException(status_code=404, detail=f"Case {case_id} not found")


@router.post("/cases/batch", status_code=201)
async def batch_create_cases(
    payload: dict,
):
    """批量创建评测用例"""
    cases = payload.get("cases", [])
    dataset_id = payload.get("dataset_id", "")
    created = []
    for c in cases:
        case_id = str(uuid.uuid4())
        created.append({
            "id": case_id,
            "dataset_id": dataset_id,
            "input": c.get("input", ""),
            "expected_output": c.get("expected_output", ""),
            "metadata": c.get("metadata", {}),
        })
    return {"created": len(created), "cases": created}


@router.post("/runs/{run_id}/metrics")
async def compute_metrics(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """计算评估运行指标"""
    try:
        uid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid run_id: {run_id}")

    result = await db.execute(
        select(EvaluationRecord).where(EvaluationRecord.id == uid)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return {
        "run_id": run_id,
        "overall_score": record.overall_score,
        "passed": record.passed,
        "dimension_scores": record.dimension_scores or [],
        "issues_count": len(record.issues or []),
        "execution_time_ms": record.execution_time_ms,
    }
