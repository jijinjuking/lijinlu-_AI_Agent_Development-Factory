"""W18 Tool Metrics — 工具调用指标收集器

收集和分析工具调用过程中的指标：
  - 工具调用成功率
  - 平均执行时间
  - 超时率
  - 重试率
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..models import EvaluationMetric

logger = logging.getLogger(__name__)


@dataclass
class ToolCallRecord:
    """单次工具调用记录"""
    tool_name: str
    task_id: str
    node_id: str = ""
    success: bool = True
    execution_time_ms: float = 0.0
    error_message: str = ""
    retry_count: int = 0
    input_size_bytes: int = 0
    output_size_bytes: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ToolMetrics:
    """工具调用聚合指标"""
    tool_name: str

    # 基础统计
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0

    # 时间统计
    total_time_ms: float = 0.0
    min_time_ms: float = float("inf")
    max_time_ms: float = 0.0

    # 重试统计
    total_retries: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return self.success_calls / self.total_calls

    @property
    def avg_time_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_time_ms / self.total_calls

    @property
    def retry_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_retries / self.total_calls

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "total_calls": self.total_calls,
            "success_calls": self.success_calls,
            "failed_calls": self.failed_calls,
            "success_rate": round(self.success_rate, 4),
            "avg_time_ms": round(self.avg_time_ms, 2),
            "min_time_ms": round(self.min_time_ms, 2) if self.min_time_ms != float("inf") else 0,
            "max_time_ms": round(self.max_time_ms, 2),
            "total_retries": self.total_retries,
            "retry_rate": round(self.retry_rate, 4),
        }


class ToolMetricsCollector:
    """工具调用指标收集器。

    用法：
        collector = ToolMetricsCollector()
        collector.record(ToolCallRecord(tool_name="git_commit", success=True, ...))
        metrics = collector.get_metrics("git_commit")
        summary = collector.get_summary()
    """

    def __init__(self):
        self._records: Dict[str, List[ToolCallRecord]] = defaultdict(list)

    # ------------------------------------------------------------------
    # 记录
    # ------------------------------------------------------------------

    def record(
        self,
        record_or_name: ToolCallRecord | str,
        success: bool = True,
        execution_time_ms: float = 0.0,
        error: str = "",
    ) -> None:
        """记录一次工具调用。

        支持两种调用方式：
          - record(ToolCallRecord(...))  # 传入完整对象
          - record("tool_name", True, 50.0, error="Timeout")  # 直接传参
        """
        if isinstance(record_or_name, ToolCallRecord):
            self._records[record_or_name.tool_name].append(record_or_name)
        else:
            record = ToolCallRecord(
                tool_name=record_or_name,
                task_id="",
                success=success,
                execution_time_ms=execution_time_ms,
                error_message=error,
            )
            self._records[record.tool_name].append(record)

    def record_batch(self, records: List[ToolCallRecord]) -> None:
        """批量记录工具调用。"""
        for r in records:
            self.record(r)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_metrics(self, tool_name: str) -> Optional[ToolMetrics]:
        """获取指定工具的聚合指标。"""
        records = self._records.get(tool_name, [])
        if not records:
            return None
        return self._aggregate(tool_name, records)

    def get_summary(self) -> dict:
        """获取全局工具调用摘要（dict 格式）。"""
        all_records = []
        for records in self._records.values():
            all_records.extend(records)
        if not all_records:
            return {
                "total": 0, "success": 0, "failed": 0,
                "success_rate": 1.0, "avg_latency_ms": 0.0,
            }
        total = len(all_records)
        success = sum(1 for r in all_records if r.success)
        failed = total - success
        latencies = [r.execution_time_ms for r in all_records if r.execution_time_ms > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "success_rate": success / total if total > 0 else 1.0,
            "avg_latency_ms": avg_latency,
        }

    def get_records(self) -> list:
        """获取所有工具调用记录。"""
        all_records = []
        for records in self._records.values():
            all_records.extend(records)
        return all_records

    def export_data(self) -> list:
        """导出所有记录（用于持久化）。"""
        return [
            {
                "tool_name": r.tool_name,
                "task_id": r.task_id,
                "success": r.success,
                "execution_time_ms": r.execution_time_ms,
                "error_message": r.error_message,
                "retry_count": r.retry_count,
                "timestamp": r.timestamp,
            }
            for r in self.get_records()
        ]

    def import_data(self, data: list) -> None:
        """从导出的数据恢复记录。"""
        for d in data:
            self.record(ToolCallRecord(
                tool_name=d["tool_name"],
                task_id=d.get("task_id", ""),
                success=d.get("success", True),
                execution_time_ms=d.get("execution_time_ms", 0.0),
                error_message=d.get("error_message", ""),
                retry_count=d.get("retry_count", 0),
                timestamp=d.get("timestamp", ""),
            ))

    def get_total_metrics(self) -> ToolMetrics:
        """获取全局（跨工具）聚合指标。"""
        all_records = []
        for records in self._records.values():
            all_records.extend(records)
        return self._aggregate("__global__", all_records)

    def get_task_records(self, task_id: str) -> List[ToolCallRecord]:
        """获取指定任务的所有工具调用记录。"""
        result = []
        for records in self._records.values():
            result.extend(r for r in records if r.task_id == task_id)
        return result

    # ------------------------------------------------------------------
    # 重置
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """清空所有记录。"""
        self._records.clear()

    def reset_tool(self, tool_name: str) -> None:
        """清空指定工具的记录。"""
        self._records.pop(tool_name, None)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate(tool_name: str, records: List[ToolCallRecord]) -> ToolMetrics:
        metrics = ToolMetrics(tool_name=tool_name)
        if not records:
            return metrics

        metrics.total_calls = len(records)
        metrics.success_calls = sum(1 for r in records if r.success)
        metrics.failed_calls = metrics.total_calls - metrics.success_calls
        metrics.total_time_ms = sum(r.execution_time_ms for r in records)
        metrics.min_time_ms = min(r.execution_time_ms for r in records) if records else 0
        metrics.max_time_ms = max(r.execution_time_ms for r in records) if records else 0
        metrics.total_retries = sum(r.retry_count for r in records)

        return metrics
