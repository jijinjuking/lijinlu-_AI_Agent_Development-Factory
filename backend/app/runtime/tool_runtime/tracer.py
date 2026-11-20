"""
Tool Tracer — 工具调用追踪
记录每次 Tool 调用的详细追踪信息（输入、输出、耗时等）
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from app.runtime.tool_runtime.models import ExecutionContext, ExecutionResult, ExecutionStatus

logger = logging.getLogger(__name__)


class ToolTracer:
    """
    Tool 调用追踪器 — 替代 LangSmith 的本地追踪方案
    """

    def __init__(self):
        self._traces: list[Dict[str, Any]] = []
        self._max_traces = 1000

    def start_trace(
        self,
        tool_name: str,
        input_args: Dict[str, Any],
        context: ExecutionContext,
    ) -> str:
        """开始追踪，返回 trace_id"""
        trace_id = f"trace_{tool_name}_{int(time.time() * 1000000)}"
        self._traces.append({
            "trace_id": trace_id,
            "tool_name": tool_name,
            "input_args": input_args,
            "task_id": context.task_id,
            "agent_id": context.agent_id,
            "start_time": time.time(),
            "status": "running",
            "result": None,
            "error": None,
            "duration_ms": 0,
        })
        # 避免内存泄漏
        if len(self._traces) > self._max_traces:
            self._traces = self._traces[-self._max_traces:]
        return trace_id

    def end_trace(self, trace_id: str, result: ExecutionResult) -> None:
        """结束追踪"""
        for trace in self._traces:
            if trace["trace_id"] == trace_id:
                trace["status"] = result.status.value if hasattr(result.status, 'value') else str(result.status)
                trace["result"] = (result.output or "")[:500]
                trace["error"] = result.error
                trace["duration_ms"] = result.duration_ms
                if "start_time" in trace:
                    trace["duration_ms"] = int((time.time() - trace["start_time"]) * 1000)
                return

    def get_traces(
        self,
        limit: int = 50,
        tool_name: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        """获取追踪记录"""
        traces = self._traces
        if tool_name:
            traces = [t for t in traces if t.get("tool_name") == tool_name]
        if task_id:
            traces = [t for t in traces if t.get("task_id") == task_id]
        return list(reversed(traces))[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """获取追踪统计"""
        total = len(self._traces)
        completed = sum(1 for t in self._traces if t.get("status") == "completed")
        failed = sum(1 for t in self._traces if t.get("status") in ("failed", "timeout"))
        denied = sum(1 for t in self._traces if t.get("status") == "denied")
        running = sum(1 for t in self._traces if t.get("status") == "running")
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "denied": denied,
            "running": running,
        }

    def clear(self) -> None:
        """清除所有追踪记录"""
        self._traces.clear()
