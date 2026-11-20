"""
Audit Logger — 审计日志
记录所有 Tool 调用，支持 DB 持久化和内存列表查询
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.runtime.tool_runtime.models import AuditEntry, ExecutionResult, ExecutionStatus

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    审计日志器 — 记录所有 Tool 执行事件
    """

    def __init__(self, db: AsyncSession | None = None):
        self.db = db
        self._memory_log: List[AuditEntry] = []  # 内存缓冲

    async def log(
        self,
        tool_name: str,
        result: ExecutionResult,
        input_args: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        """记录审计日志到 DB 和内存缓冲"""
        entry = AuditEntry(
            tool_name=tool_name,
            status=result.status,
            task_id=task_id,
            agent_id=agent_id,
            input_args=input_args or {},
            output_summary=(result.output or "")[:500],
            error=result.error,
            duration_ms=result.duration_ms,
            exit_code=result.exit_code,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        self._memory_log.append(entry)

        # 持久化到 DB
        if self.db:
            try:
                from app.models.tool import ToolExecution
                execution = ToolExecution(
                    tool_name=tool_name,
                    task_id=task_id,
                    agent_id=agent_id,
                    status=result.status.value if hasattr(result.status, 'value') else str(result.status),
                    input_args=input_args or {},
                    output_result=(result.output or "")[:2000],
                    output_error=result.error,
                    duration_ms=result.duration_ms,
                    exit_code=result.exit_code,
                )
                self.db.add(execution)
                await self.db.commit()
            except Exception as e:
                logger.warning("Failed to persist audit log: %s", e)

    async def get_recent(
        self,
        limit: int = 50,
        tool_name: Optional[str] = None,
    ) -> List[AuditEntry]:
        """获取最近审计日志"""
        entries = self._memory_log
        if tool_name:
            entries = [e for e in entries if e.tool_name == tool_name]
        return entries[-limit:]

    async def get_from_db(
        self,
        db: AsyncSession,
        limit: int = 50,
        tool_name: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """从 DB 查询审计日志"""
        from app.models.tool import ToolExecution
        stmt = select(ToolExecution).order_by(ToolExecution.created_at.desc())
        if tool_name:
            stmt = stmt.where(ToolExecution.tool_name == tool_name)
        if task_id:
            stmt = stmt.where(ToolExecution.task_id == task_id)
        stmt = stmt.limit(limit)

        result = await db.execute(stmt)
        rows = result.scalars().all()

        return [
            {
                "id": str(r.id),
                "tool_name": r.tool_name,
                "task_id": r.task_id,
                "agent_id": r.agent_id,
                "status": r.status,
                "input_args": r.input_args,
                "output_result": r.output_result[:500] if r.output_result else None,
                "output_error": r.output_error,
                "duration_ms": r.duration_ms,
                "exit_code": r.exit_code,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    async def get_stats(self, db: AsyncSession) -> Dict[str, Any]:
        """获取审计统计信息"""
        from app.models.tool import ToolExecution
        total = await db.scalar(select(func.count()).select_from(ToolExecution))
        completed = await db.scalar(
            select(func.count()).select_from(ToolExecution).where(ToolExecution.status == "completed")
        )
        failed = await db.scalar(
            select(func.count()).select_from(ToolExecution).where(ToolExecution.status.in_(["failed", "timeout"]))
        )
        denied = await db.scalar(
            select(func.count()).select_from(ToolExecution).where(ToolExecution.status == "denied")
        )
        return {
            "total": total or 0,
            "completed": completed or 0,
            "failed": failed or 0,
            "denied": denied or 0,
        }

    def clear_memory(self) -> None:
        """清除内存中的日志"""
        self._memory_log.clear()
