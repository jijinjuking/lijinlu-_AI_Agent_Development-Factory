"""
W18 Self Evaluation — 评估记录持久化模型

存储每次评估的完整结果：
  - 综合得分、各维度得分
  - 发现的问题（issues）
  - 改进建议
  - 关联的 task_id / agent_id
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.database import Base
from app.models.base import UUIDPrimaryKey, TimestampMixin


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EvaluationRecord(Base, UUIDPrimaryKey, TimestampMixin):
    """评估记录 — 对应 runtime.evaluation.EvaluationResult"""

    __tablename__ = "evaluation_records"

    # 关联
    task_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(255), default="")
    agent_id: Mapped[str] = mapped_column(String(36), default="")
    agent_name: Mapped[str] = mapped_column(String(255), default="")

    # 评估范围
    scope: Mapped[str] = mapped_column(String(20), default="task")  # task / node / step

    # 综合得分（0.0 ~ 1.0）
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    passed: Mapped[bool] = mapped_column(default=False)
    threshold: Mapped[float] = mapped_column(Float, default=0.7)

    # 各维度得分 — JSON，如 {"task_success": 0.9, "hallucination": 0.8, ...}
    dimension_scores: Mapped[dict | None] = mapped_column(JSON, default=None)

    # 问题列表 — JSON，如 [{"code": "...", "severity": "major", "message": "...", ...}]
    issues: Mapped[list | None] = mapped_column(JSON, default=None)

    # 改进建议
    suggestions: Mapped[list | None] = mapped_column(JSON, default=None)

    # 执行上下文（快照）
    context_snapshot: Mapped[dict | None] = mapped_column(JSON, default=None)

    # 评估耗时（毫秒）
    execution_time_ms: Mapped[float] = mapped_column(Float, default=0.0)

    # 评估器信息
    evaluator_version: Mapped[str] = mapped_column(String(20), default="1.0")
    evaluation_timestamp: Mapped[str] = mapped_column(String(64), default="")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "task_id": self.task_id,
            "node_id": self.node_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "scope": self.scope,
            "overall_score": round(self.overall_score, 4),
            "passed": self.passed,
            "threshold": self.threshold,
            "dimension_scores": self.dimension_scores or [],
            "issues": self.issues or [],
            "suggestions": self.suggestions or [],
            "context_snapshot": self.context_snapshot or {},
            "execution_time_ms": round(self.execution_time_ms, 2),
            "evaluator_version": self.evaluator_version,
            "evaluation_timestamp": self.evaluation_timestamp,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }

    @classmethod
    def from_evaluation_result(cls, result, task_id: str, agent_name: str = "") -> "EvaluationRecord":
        """从 runtime 的 EvaluationResult 构造数据库记录。"""
        from app.runtime.evaluation.models import EvaluationResult
        # 转换 issues，确保所有嵌套对象都已序列化
        raw_issues = getattr(result, "issues", [])
        converted_issues = []
        for issue in raw_issues:
            if isinstance(issue, dict):
                converted_issues.append(issue)
            elif hasattr(issue, "to_dict"):
                converted_issues.append(issue.to_dict())
            else:
                converted_issues.append(str(issue))

        # 转换 dimension_scores
        raw_scores = getattr(result, "dimension_scores", [])
        converted_scores = []
        for ds in raw_scores:
            if isinstance(ds, dict):
                converted_scores.append(ds)
            elif hasattr(ds, "to_dict"):
                converted_scores.append(ds.to_dict())
            else:
                converted_scores.append(str(ds))

        record = cls(
            task_id=task_id,
            node_id=getattr(result, "node_id", ""),
            agent_name=agent_name or getattr(result, "agent_name", ""),
            scope=getattr(result, "scope", None) and result.scope.value if hasattr(result.scope, "value") else str(getattr(result, "scope", "task")),
            overall_score=result.overall_score,
            passed=result.passed,
            threshold=getattr(result, "threshold", 0.7),
            dimension_scores=converted_scores,
            issues=converted_issues,
            suggestions=[str(s) if not isinstance(s, str) else s for s in getattr(result, "suggestions", [])],
            execution_time_ms=getattr(result, "execution_time_ms", 0.0),
            evaluation_timestamp=getattr(result, "timestamp", ""),
        )
        return record
