"""W33-34 Multi-Tenant — 租户管理器

租户 CRUD、生命周期管理、成员管理、统计。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .models import (
    AuditEventType,
    CrossTenantPolicy,
    IsolationMode,
    QuotaCheckResult,
    QuotaStatus,
    ResourceQuota,
    ResourceType,
    Tenant,
    TenantAuditRecord,
    TenantConfig,
    TenantFilter,
    TenantMember,
    TenantStats,
    TenantStatus,
)

logger = logging.getLogger(__name__)


class TenantManager:
    """租户管理器 — 核心 CRUD + 生命周期"""

    def __init__(self):
        self._tenants: dict[str, Tenant] = {}
        self._members: dict[str, list[TenantMember]] = {}  # tenant_id → members
        self._user_tenants: dict[str, list[str]] = {}      # user_id → tenant_ids

    # ── CRUD ──────────────────────────────────

    def create_tenant(self, config: TenantConfig) -> Tenant:
        """创建租户"""
        # slug 唯一性检查
        for t in self._tenants.values():
            if t.slug == config.tenant_slug:
                raise ValueError(f"Tenant slug '{config.tenant_slug}' already exists")

        tenant = Tenant(
            name=config.tenant_name,
            slug=config.tenant_slug,
            isolation_mode=config.isolation_mode,
            cross_tenant_policy=config.cross_tenant_policy,
            allowed_tenant_ids=list(config.allowed_tenant_ids),
            tags=dict(config.tags),
            metadata=dict(config.metadata),
        )
        self._tenants[tenant.tenant_id] = tenant
        self._members.setdefault(tenant.tenant_id, [])
        logger.info("Tenant created: %s (%s)", tenant.name, tenant.tenant_id)
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)

    def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        for t in self._tenants.values():
            if t.slug == slug:
                return t
        return None

    def list_tenants(self, status: TenantStatus | None = None,
                     isolation_mode: IsolationMode | None = None,
                     tag_filter: dict[str, str] | None = None) -> list[Tenant]:
        """列出所有租户，支持筛选"""
        result = list(self._tenants.values())
        if status:
            result = [t for t in result if t.status == status]
        if isolation_mode:
            result = [t for t in result if t.isolation_mode == isolation_mode]
        if tag_filter:
            result = [t for t in result
                      if all(t.tags.get(k) == v for k, v in tag_filter.items())]
        result.sort(key=lambda t: t.created_at, reverse=True)
        return result

    def delete_tenant(self, tenant_id: str) -> bool:
        """删除租户（仅允许 ARCHIVED 状态）"""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False
        if tenant.status != TenantStatus.ARCHIVED:
            raise ValueError(f"Cannot delete tenant in '{tenant.status.value}' status. Archive first.")
        del self._tenants[tenant_id]
        self._members.pop(tenant_id, None)
        return True

    # ── 生命周期管理 ──────────────────────────

    def activate_tenant(self, tenant_id: str) -> Tenant:
        """激活租户"""
        tenant = self._require_tenant(tenant_id)
        valid_from = {TenantStatus.PENDING, TenantStatus.SUSPENDED}
        if tenant.status not in valid_from:
            raise ValueError(
                f"Cannot activate tenant from '{tenant.status.value}'. "
                f"Must be {[s.value for s in valid_from]}"
            )
        tenant.status = TenantStatus.ACTIVE
        tenant.activated_at = datetime.now()
        tenant.updated_at = datetime.now()
        logger.info("Tenant activated: %s", tenant.name)
        return tenant

    def suspend_tenant(self, tenant_id: str, reason: str = "") -> Tenant:
        """暂停租户"""
        tenant = self._require_tenant(tenant_id)
        if tenant.status != TenantStatus.ACTIVE:
            raise ValueError(
                f"Cannot suspend tenant in '{tenant.status.value}' status"
            )
        tenant.status = TenantStatus.SUSPENDED
        tenant.suspended_at = datetime.now()
        tenant.suspended_reason = reason
        tenant.updated_at = datetime.now()
        logger.warning("Tenant suspended: %s (reason: %s)", tenant.name, reason)
        return tenant

    def archive_tenant(self, tenant_id: str) -> Tenant:
        """归档租户（软删除）"""
        tenant = self._require_tenant(tenant_id)
        if tenant.status == TenantStatus.ARCHIVED:
            return tenant  # already archived
        tenant.status = TenantStatus.ARCHIVED
        tenant.updated_at = datetime.now()
        logger.info("Tenant archived: %s", tenant.name)
        return tenant

    def update_tenant(self, tenant_id: str, **kwargs) -> Tenant:
        """更新租户属性"""
        tenant = self._require_tenant(tenant_id)
        updatable = {
            "name", "cross_tenant_policy", "allowed_tenant_ids",
            "tags", "metadata",
        }
        for k, v in kwargs.items():
            if k in updatable:
                if k == "allowed_tenant_ids":
                    setattr(tenant, k, list(v))
                elif k in ("tags", "metadata"):
                    setattr(tenant, k, dict(v))
                else:
                    setattr(tenant, k, v)
            else:
                logger.warning("Ignored non-updatable field '%s' for tenant %s", k, tenant_id)
        tenant.updated_at = datetime.now()
        return tenant

    # ── 成员管理 ──────────────────────────────

    def add_member(self, tenant_id: str, user_id: str,
                   role: str = "member",
                   permissions: list[str] | None = None) -> TenantMember:
        """向租户添加成员"""
        self._require_tenant(tenant_id)
        # 去重
        existing = self._members.get(tenant_id, [])
        for m in existing:
            if m.user_id == user_id:
                return m  # already a member

        member = TenantMember(
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            permissions=list(permissions or []),
        )
        self._members.setdefault(tenant_id, []).append(member)
        self._user_tenants.setdefault(user_id, []).append(tenant_id)
        return member

    def remove_member(self, tenant_id: str, user_id: str) -> bool:
        """从租户移除成员"""
        members = self._members.get(tenant_id, [])
        target = None
        for m in members:
            if m.user_id == user_id:
                target = m
                break
        if target:
            members.remove(target)
            user_tenants = self._user_tenants.get(user_id, [])
            if tenant_id in user_tenants:
                user_tenants.remove(tenant_id)
            return True
        return False

    def get_tenant_members(self, tenant_id: str) -> list[TenantMember]:
        self._require_tenant(tenant_id)
        return list(self._members.get(tenant_id, []))

    def get_user_tenants(self, user_id: str) -> list[str]:
        return list(self._user_tenants.get(user_id, []))

    # ── 配额操作 ──────────────────────────────

    def set_quota(self, tenant_id: str, resource_type: ResourceType,
                  limit: float, alert_threshold: float = 0.8,
                  is_hard_limit: bool = True):
        """设置资源配额"""
        tenant = self._require_tenant(tenant_id)
        tenant.quota.set_limit(resource_type, limit, alert_threshold, is_hard_limit)
        tenant.updated_at = datetime.now()

    def check_quota(self, tenant_id: str, resource_type: ResourceType,
                    requested: float = 1) -> QuotaStatus:
        """检查配额"""
        tenant = self._require_tenant(tenant_id)
        return tenant.quota.check(resource_type, requested)

    def check_all_quotas(self, tenant_id: str,
                         requests: dict[ResourceType, float] | None = None
                         ) -> QuotaCheckResult:
        """批量检查所有配额"""
        tenant = self._require_tenant(tenant_id)
        exceeded = []
        warning = []
        requests = requests or {}

        for rt, quota in tenant.quota.quotas.items():
            req = requests.get(rt, 0)
            status = tenant.quota.check(rt, req)
            if status == QuotaStatus.EXCEEDED:
                exceeded.append(rt)
            elif status == QuotaStatus.WARNING:
                warning.append(rt)

        if exceeded:
            return QuotaCheckResult(
                allowed=False,
                status=QuotaStatus.EXCEEDED,
                exceeded_resources=exceeded,
                warning_resources=warning,
                message=f"Exceeded quotas: {[e.value for e in exceeded]}",
            )
        if warning:
            return QuotaCheckResult(
                allowed=True,
                status=QuotaStatus.WARNING,
                warning_resources=warning,
                message=f"Warning quotas: {[w.value for w in warning]}",
            )
        return QuotaCheckResult(allowed=True)

    def consume_quota(self, tenant_id: str, resource_type: ResourceType,
                      amount: float = 1) -> QuotaStatus:
        """消费配额"""
        tenant = self._require_tenant(tenant_id)
        return tenant.quota.consume(resource_type, amount)

    def release_quota(self, tenant_id: str, resource_type: ResourceType,
                      amount: float = 1):
        """释放配额"""
        tenant = self._require_tenant(tenant_id)
        tenant.quota.release(resource_type, amount)

    # ── 隔离检查 ──────────────────────────────

    def check_cross_tenant_access(self, source_tenant_id: str,
                                  target_tenant_id: str) -> bool:
        """检查跨租户访问是否允许"""
        if source_tenant_id == target_tenant_id:
            return True
        source = self._require_tenant(source_tenant_id)
        if source.cross_tenant_policy == CrossTenantPolicy.OPEN:
            return True
        if source.cross_tenant_policy == CrossTenantPolicy.BLOCK_ALL:
            return False
        if source.cross_tenant_policy == CrossTenantPolicy.ALLOW_LIST:
            return target_tenant_id in source.allowed_tenant_ids
        return False

    def create_filter(self, tenant_id: str) -> TenantFilter:
        """为数据访问层创建租户过滤器"""
        tenant = self._require_tenant(tenant_id)
        return TenantFilter(
            tenant_id=tenant_id,
            isolation_mode=tenant.isolation_mode,
        )

    # ── 统计 ──────────────────────────────────

    def get_tenant_stats(self, tenant_id: str) -> TenantStats:
        """获取租户统计"""
        tenant = self._require_tenant(tenant_id)
        return TenantStats(
            tenant_id=tenant_id,
            tenant_name=tenant.name,
            total_members=len(self._members.get(tenant_id, [])),
            quota_summary=tenant.quota.to_summary(),
        )

    def get_all_stats(self) -> list[TenantStats]:
        """获取所有租户统计"""
        return [self.get_tenant_stats(tid) for tid in self._tenants]

    # ── 内部 ──────────────────────────────────

    def _require_tenant(self, tenant_id: str) -> Tenant:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant '{tenant_id}' not found")
        return tenant

    @property
    def tenant_count(self) -> int:
        return len(self._tenants)
