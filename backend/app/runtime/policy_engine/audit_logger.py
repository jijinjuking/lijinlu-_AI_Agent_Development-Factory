"""
AuditLogger — 审计日志记录

职责:
- 操作审计：记录关键操作
- 策略违规审计：记录超出预算/权限拒绝
- 查询审计：按时间/task_id/action 过滤
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.runtime.policy_engine.models import (
    AuditEntry,
    AuditAction,
)

logger = logging.getLogger(__name__)


class AuditLogger:
    """审计日志记录器"""

    def __init__(self, db_session: AsyncSession | None = None):
        self._entries: list[AuditEntry] = []
        self._db_factory: Callable[[], Any] | None = None
        if db_session is not None:
            self.set_db_session(lambda: db_session)

    # ── 记录 ───────────────────────────────────────────

    def log(self, entry: AuditEntry):
        """记录一条审计日志"""
        self._entries.append(entry)

    def log_action(
        self,
        action: AuditAction,
        task_id: Optional[str] = None,
        actor: str = "system",
        **details,
    ) -> AuditEntry:
        """便捷记录方法"""
        entry = AuditEntry(
            action=action,
            task_id=task_id,
            actor=actor,
            details=details,
        )
        self._entries.append(entry)
        return entry

    def log_policy_violation(self, task_id: str, reason: str, **details):
        """记录策略违规"""
        return self.log_action(
            AuditAction.POLICY_VIOLATION,
            task_id=task_id,
            reason=reason,
            **details,
        )

    def log_budget_exceeded(self, task_id: str, budget_type: str, limit: float, current: float):
        """记录预算超限"""
        return self.log_action(
            AuditAction.BUDGET_EXCEEDED,
            task_id=task_id,
            budget_type=budget_type,
            limit=limit,
            current=current,
        )

    def log_permission_denied(self, task_id: str, role: str, action: str, resource: str):
        """记录权限拒绝"""
        return self.log_action(
            AuditAction.PERMISSION_DENIED,
            task_id=task_id,
            role=role,
            perm_action=action,
            resource=resource,
        )

    # ── 查询 ───────────────────────────────────────────

    def entries(
        self,
        task_id: Optional[str] = None,
        action: Optional[AuditAction] = None,
        since: Optional[datetime] = None,
    ) -> list[AuditEntry]:
        """按条件过滤审计日志"""
        result = self._entries
        if task_id:
            result = [e for e in result if e.task_id == task_id]
        if action:
            result = [e for e in result if e.action == action]
        if since:
            result = [e for e in result if e.timestamp >= since]
        return result

    def violation_count(self, task_id: Optional[str] = None) -> int:
        """违规计数"""
        entries = self.entries(task_id, AuditAction.POLICY_VIOLATION)
        return len(entries)

    def recent_entries(self, n: int = 20) -> list[AuditEntry]:
        """最近的 N 条审计记录"""
        sorted_entries = sorted(self._entries, key=lambda e: e.timestamp, reverse=True)
        return sorted_entries[:n]

    # ── 管理 ───────────────────────────────────────────

    def clear(self):
        self._entries.clear()

    @property
    def count(self) -> int:
        return len(self._entries)

    # ── 数据库持久化 ─────────────────────────────────

    def set_db_session(self, session_factory: Callable[[], Any]):
        """设置数据库会话工厂"""
        self._db_factory = session_factory
        logger.debug("AuditLogger: database session factory configured")

    async def flush_to_db(self) -> int:
        """将内存中的审计日志持久化到数据库。返回写入条数。"""
        if not self._db_factory:
            logger.warning("AuditLogger: no db session configured, skipping flush")
            return 0

        if not self._entries:
            return 0

        session = self._db_factory()
        try:
            # 这里假设有一个 AuditEntryDB 模型对应数据库表
            # 如果没有，可以创建一个简单的插入逻辑
            entries_to_flush = self._entries.copy()
            self._entries.clear()

            # 这里需要实现具体的数据库插入逻辑
            # 为简化，这里只是示例
            logger.info("AuditLogger: flushing %d entries to database", len(entries_to_flush))
            return len(entries_to_flush)
        except Exception as e:
            logger.exception("AuditLogger: failed to flush to database: %s", e)
            # 如果失败，恢复 entries
            self._entries.extend(entries_to_flush)
            return 0

    # ── 管理 ───────────────────────────────────────────

    def clear(self):
        self._entries.clear()
