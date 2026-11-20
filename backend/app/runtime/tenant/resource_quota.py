"""W33-34 Multi-Tenant — 资源配额管理器

配额分配、批量检查、消费/释放、重置、额度转移、趋势分析。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .models import (
    AuditEventType,
    QuotaCheckResult,
    QuotaStatus,
    ResourceQuota,
    ResourceType,
    TenantAuditRecord,
    TenantStatus,
)

logger = logging.getLogger(__name__)


class ResourceQuotaManager:
    """资源配额管理器 — 配额策略执行"""

    def __init__(self, tenant_manager):
        from .tenant_manager import TenantManager
        self._tm: TenantManager = tenant_manager
        self._audit_records: list[TenantAuditRecord] = []

    # ── 配额操作 ──────────────────────────────

    def allocate_quota(self, tenant_id: str, resource_type: ResourceType,
                       limit: float, alert_threshold: float = 0.8) -> QuotaStatus:
        """为租户分配配额"""
        self._tm.set_quota(tenant_id, resource_type, limit, alert_threshold)
        self._log(tenant_id, AuditEventType.QUOTA_ADJUSTED,
                   resource_type=resource_type.value,
                   detail={"limit": limit, "alert_threshold": alert_threshold})
        return QuotaStatus.OK

    def allocate_default_quotas(self, tenant_id: str, tier: str = "standard"):
        """根据套餐等级分配默认配额"""
        tiers = {
            "free": {
                ResourceType.CPU_CORES: 1,
                ResourceType.MEMORY_MB: 512,
                ResourceType.STORAGE_MB: 1024,
                ResourceType.API_CALLS_PER_DAY: 100,
                ResourceType.MAX_CONCURRENCY: 2,
                ResourceType.TOKENS_PER_DAY: 10000,
                ResourceType.TASKS_PER_DAY: 50,
                ResourceType.AGENTS_MAX: 3,
            },
            "standard": {
                ResourceType.CPU_CORES: 4,
                ResourceType.MEMORY_MB: 4096,
                ResourceType.STORAGE_MB: 10240,
                ResourceType.API_CALLS_PER_DAY: 10000,
                ResourceType.MAX_CONCURRENCY: 10,
                ResourceType.TOKENS_PER_DAY: 1000000,
                ResourceType.TASKS_PER_DAY: 5000,
                ResourceType.AGENTS_MAX: 20,
            },
            "enterprise": {
                ResourceType.CPU_CORES: 32,
                ResourceType.MEMORY_MB: 32768,
                ResourceType.STORAGE_MB: 102400,
                ResourceType.API_CALLS_PER_DAY: 1000000,
                ResourceType.MAX_CONCURRENCY: 100,
                ResourceType.TOKENS_PER_DAY: 100000000,
                ResourceType.TASKS_PER_DAY: 500000,
                ResourceType.AGENTS_MAX: 200,
            },
        }

        plan = tiers.get(tier, tiers["standard"])
        for rt, limit in plan.items():
            self._tm.set_quota(tenant_id, rt, limit)

        logger.info("Default '%s' quotas allocated for tenant %s", tier, tenant_id)

    def try_consume(self, tenant_id: str, resource_type: ResourceType,
                    amount: float = 1) -> QuotaCheckResult:
        """尝试消费配额 — 检查 + 消费"""
        tenant = self._tm.get_tenant(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant '{tenant_id}' not found")
        if not tenant.status.is_operational:
            return QuotaCheckResult(
                allowed=False,
                status=QuotaStatus.EXCEEDED,
                message=f"Tenant is {tenant.status.value}",
            )

        status = self._tm.consume_quota(tenant_id, resource_type, amount)
        quota = tenant.quota.get(resource_type)
        self._log(tenant_id, AuditEventType.RESOURCE_CONSUMED,
                   resource_type=resource_type.value,
                   detail={"amount": amount, "status": status.value})

        if status == QuotaStatus.EXCEEDED:
            self._log(tenant_id, AuditEventType.QUOTA_EXCEEDED,
                       resource_type=resource_type.value,
                       detail={"used": quota.used if quota else 0,
                               "limit": quota.limit if quota else 0})
            return QuotaCheckResult(
                allowed=False, status=status,
                exceeded_resources=[resource_type],
                message=f"Quota exceeded: {resource_type.value}",
            )
        if status == QuotaStatus.WARNING:
            return QuotaCheckResult(
                allowed=True, status=status,
                warning_resources=[resource_type],
                message=f"Quota warning: {resource_type.value}",
            )
        return QuotaCheckResult(allowed=True)

    def batch_consume(self, tenant_id: str,
                      requests: dict[ResourceType, float]) -> QuotaCheckResult:
        """批量消费 — 先检查所有，再统一消费（原子性）"""
        tenant = self._tm.get_tenant(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant '{tenant_id}' not found")
        if not tenant.status.is_operational:
            return QuotaCheckResult(
                allowed=False,
                status=QuotaStatus.EXCEEDED,
                message=f"Tenant is {tenant.status.value}",
            )

        # 先检查
        exceeded = []
        warning = []
        for rt, amount in requests.items():
            status = tenant.quota.check(rt, amount)
            if status == QuotaStatus.EXCEEDED:
                exceeded.append(rt)
            elif status == QuotaStatus.WARNING:
                warning.append(rt)

        if exceeded:
            return QuotaCheckResult(
                allowed=False, status=QuotaStatus.EXCEEDED,
                exceeded_resources=exceeded, warning_resources=warning,
            )

        # 全部通过 → 统一消费
        for rt, amount in requests.items():
            self._tm.consume_quota(tenant_id, rt, amount)
            self._log(tenant_id, AuditEventType.RESOURCE_CONSUMED,
                       resource_type=rt.value, detail={"amount": amount})

        if warning:
            return QuotaCheckResult(
                allowed=True, status=QuotaStatus.WARNING,
                warning_resources=warning,
            )
        return QuotaCheckResult(allowed=True)

    def release(self, tenant_id: str, resource_type: ResourceType,
                amount: float = 1):
        """释放资源"""
        self._tm.release_quota(tenant_id, resource_type, amount)
        self._log(tenant_id, AuditEventType.RESOURCE_RELEASED,
                   resource_type=resource_type.value,
                   detail={"amount": amount})

    def batch_release(self, tenant_id: str,
                      releases: dict[ResourceType, float]):
        """批量释放"""
        for rt, amount in releases.items():
            self._tm.release_quota(tenant_id, rt, amount)
            self._log(tenant_id, AuditEventType.RESOURCE_RELEASED,
                       resource_type=rt.value, detail={"amount": amount})

    def reset_usage(self, tenant_id: str):
        """重置使用量（清零所有 used）"""
        tenant = self._tm.get_tenant(tenant_id)
        if not tenant:
            return
        for quota in tenant.quota.quotas.values():
            quota.used = 0.0

    def reset_all_usage(self):
        """重置所有租户使用量"""
        for tenant in self._tm._tenants.values():
            for quota in tenant.quota.quotas.values():
                quota.used = 0.0

    def transfer_quota(self, from_tenant_id: str, to_tenant_id: str,
                       resource_type: ResourceType, amount: float) -> QuotaCheckResult:
        """在两个租户间转移配额"""
        from_tenant = self._tm.get_tenant(from_tenant_id)
        to_tenant = self._tm.get_tenant(to_tenant_id)
        if not from_tenant or not to_tenant:
            raise ValueError("Tenant not found")

        from_quota = from_tenant.quota.get(resource_type)
        if not from_quota or from_quota.remaining < amount:
            return QuotaCheckResult(
                allowed=False, status=QuotaStatus.EXCEEDED,
                exceeded_resources=[resource_type],
                message="Insufficient quota to transfer",
            )

        self._tm.consume_quota(from_tenant_id, resource_type, amount)
        to_tenant.quota.set_limit(
            resource_type,
            (to_tenant.quota.get(resource_type).limit
             if to_tenant.quota.get(resource_type) else 0) + amount,
        )
        return QuotaCheckResult(allowed=True)

    # ── 配额查询 ──────────────────────────────

    def get_quota_summary(self, tenant_id: str) -> dict:
        """获取配额摘要"""
        tenant = self._tm.get_tenant(tenant_id)
        if not tenant:
            return {}
        return tenant.quota.to_summary()

    def get_all_exceeded(self) -> list[dict[str, Any]]:
        """获取所有超额租户"""
        result = []
        for tenant in self._tm._tenants.values():
            for rt, quota in tenant.quota.quotas.items():
                if quota.status == QuotaStatus.EXCEEDED:
                    result.append({
                        "tenant_id": tenant.tenant_id,
                        "tenant_name": tenant.name,
                        "resource": rt.value,
                        "used": quota.used,
                        "limit": quota.limit,
                    })
        return result

    def get_all_warnings(self) -> list[dict[str, Any]]:
        """获取所有警告租户"""
        result = []
        for tenant in self._tm._tenants.values():
            for rt, quota in tenant.quota.quotas.items():
                if quota.status == QuotaStatus.WARNING:
                    result.append({
                        "tenant_id": tenant.tenant_id,
                        "tenant_name": tenant.name,
                        "resource": rt.value,
                        "used": quota.used,
                        "limit": quota.limit,
                        "usage_pct": round(quota.usage_pct * 100, 1),
                    })
        return result

    def get_usage_trends(self, tenant_id: str) -> dict[str, list[dict]]:
        """获取使用趋势（简化版 — 基于当前快照 + 审计日志）"""
        records = [r for r in self._audit_records
                    if r.tenant_id == tenant_id
                    and r.event_type == AuditEventType.RESOURCE_CONSUMED]
        trends: dict[str, list[dict]] = {}
        for r in records:
            rt = r.resource_type
            if rt not in trends:
                trends[rt] = []
            trends[rt].append({
                "amount": r.detail.get("amount", 0),
                "timestamp": r.timestamp.isoformat(),
            })
        return trends

    # ── 审计日志 ──────────────────────────────

    def get_audit_logs(self, tenant_id: str = "",
                       limit: int = 100, offset: int = 0) -> list[TenantAuditRecord]:
        """获取审计日志"""
        records = self._audit_records
        if tenant_id:
            records = [r for r in records if r.tenant_id == tenant_id]
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records[offset:offset + limit]

    def _log(self, tenant_id: str, event_type: AuditEventType,
             resource_type: str = "", detail: dict | None = None):
        record = TenantAuditRecord(
            tenant_id=tenant_id,
            event_type=event_type,
            actor_type="system",
            resource_type=resource_type,
            detail=detail or {},
            timestamp=datetime.now(),
        )
        self._audit_records.append(record)
