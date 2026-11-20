"""W33-34 Multi-Tenant — 租户审计日志

租户级审计日志记录、查询、统计和导出。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .models import (
    AuditEventType,
    AuditQuery,
    TenantAuditRecord,
)

logger = logging.getLogger(__name__)


class TenantAuditLogger:
    """租户审计日志器 — 审计记录、查询、统计"""

    def __init__(self, capacity: int = 10000):
        self._records: list[TenantAuditRecord] = []
        self._capacity = capacity

    # ── 记录 ──────────────────────────────────

    def log(self, tenant_id: str, event_type: AuditEventType,
            actor_id: str = "", actor_type: str = "system",
            resource_type: str = "", resource_id: str = "",
            detail: dict[str, Any] | None = None,
            success: bool = True, error_message: str = "") -> TenantAuditRecord:
        """记录一条审计日志"""
        record = TenantAuditRecord(
            tenant_id=tenant_id,
            event_type=event_type,
            actor_id=actor_id,
            actor_type=actor_type,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail or {},
            timestamp=datetime.now(),
            success=success,
            error_message=error_message,
        )
        self._records.append(record)

        # 容量限制：超过上限淘汰最旧的
        if len(self._records) > self._capacity:
            self._records = self._records[-self._capacity:]

        return record

    def log_tenant_event(self, tenant_id: str, event_type: AuditEventType,
                         actor_id: str = "system",
                         detail: dict[str, Any] | None = None):
        """快捷记录租户事件"""
        return self.log(
            tenant_id=tenant_id,
            event_type=event_type,
            actor_id=actor_id,
            resource_type="tenant",
            resource_id=tenant_id,
            detail=detail,
        )

    # ── 查询 ──────────────────────────────────

    def query(self, query_params: AuditQuery) -> list[TenantAuditRecord]:
        """查询审计记录"""
        records = self._records

        if query_params.tenant_id:
            records = [r for r in records if r.tenant_id == query_params.tenant_id]
        if query_params.event_type:
            records = [r for r in records if r.event_type == query_params.event_type]
        if query_params.actor_id:
            records = [r for r in records if r.actor_id == query_params.actor_id]
        if query_params.resource_type:
            records = [r for r in records
                       if r.resource_type == query_params.resource_type]
        if query_params.start_time:
            records = [r for r in records
                       if r.timestamp >= query_params.start_time]
        if query_params.end_time:
            records = [r for r in records
                       if r.timestamp <= query_params.end_time]

        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records[query_params.offset:query_params.offset + query_params.limit]

    def get_by_tenant(self, tenant_id: str,
                      limit: int = 100, offset: int = 0) -> list[TenantAuditRecord]:
        """获取指定租户的审计记录"""
        return self.query(AuditQuery(
            tenant_id=tenant_id, limit=limit, offset=offset,
        ))

    def get_by_event_type(self, event_type: AuditEventType,
                          limit: int = 100, offset: int = 0) -> list[TenantAuditRecord]:
        """按事件类型查询"""
        return self.query(AuditQuery(
            event_type=event_type, limit=limit, offset=offset,
        ))

    def get_violations(self, tenant_id: str = "",
                       limit: int = 100) -> list[TenantAuditRecord]:
        """查询违规记录"""
        return self.query(AuditQuery(
            tenant_id=tenant_id,
            event_type=AuditEventType.ISOLATION_VIOLATION,
            limit=limit,
        ))

    def get_quota_exceeded(self, tenant_id: str = "",
                           limit: int = 100) -> list[TenantAuditRecord]:
        """查询配额超限记录"""
        return self.query(AuditQuery(
            tenant_id=tenant_id,
            event_type=AuditEventType.QUOTA_EXCEEDED,
            limit=limit,
        ))

    # ── 统计 ──────────────────────────────────

    def get_stats(self, tenant_id: str = "") -> dict[str, Any]:
        """获取审计统计"""
        records = self._records
        if tenant_id:
            records = [r for r in records if r.tenant_id == tenant_id]

        by_type: dict[str, int] = {}
        by_tenant: dict[str, int] = {}
        success_count = 0
        fail_count = 0

        for r in records:
            by_type[r.event_type.value] = by_type.get(r.event_type.value, 0) + 1
            by_tenant[r.tenant_id] = by_tenant.get(r.tenant_id, 0) + 1
            if r.success:
                success_count += 1
            else:
                fail_count += 1

        return {
            "total": len(records),
            "success": success_count,
            "failed": fail_count,
            "by_type": by_type,
            "by_tenant": by_tenant,
        }

    def get_tenant_timeline(self, tenant_id: str, limit: int = 50
                            ) -> list[dict[str, Any]]:
        """获取租户事件时间线"""
        records = [r for r in self._records if r.tenant_id == tenant_id]
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return [
            {
                "event": r.event_type.value,
                "actor": r.actor_id,
                "resource": r.resource_type,
                "timestamp": r.timestamp.isoformat(),
                "success": r.success,
            }
            for r in records[:limit]
        ]

    # ── 清理 ──────────────────────────────────

    def purge_older_than(self, before: datetime) -> int:
        """清理指定时间之前的记录"""
        old_count = len(self._records)
        self._records = [r for r in self._records if r.timestamp >= before]
        removed = old_count - len(self._records)
        logger.info("Purged %d audit records older than %s", removed, before)
        return removed

    def purge_tenant(self, tenant_id: str) -> int:
        """清理指定租户的审计记录"""
        old_count = len(self._records)
        self._records = [r for r in self._records if r.tenant_id != tenant_id]
        return old_count - len(self._records)

    def clear(self):
        """清空所有记录"""
        self._records = []

    @property
    def record_count(self) -> int:
        return len(self._records)
