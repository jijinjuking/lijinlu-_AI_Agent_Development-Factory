"""W33-34 Multi-Tenant 隔离 — 多租户隔离系统

Multi-Tenant 模块提供多租户隔离能力：
- TenantManager：租户 CRUD 与生命周期管理
- ResourceQuotaManager：资源配额追踪与执行
- DataIsolator：数据隔离策略（Schema/Row-Level/Hybrid/Shared）
- IsolationPolicy：租户间访问控制
- TenantAuditLogger：租户审计日志
"""

from app.runtime.tenant.models import (
    AuditEventType,
    AuditQuery,
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
    TenantQuota,
    TenantStats,
    TenantStatus,
)
from app.runtime.tenant.tenant_manager import TenantManager
from app.runtime.tenant.resource_quota import ResourceQuotaManager
from app.runtime.tenant.data_isolator import DataIsolator
from app.runtime.tenant.isolation_policy import IsolationPolicy
from app.runtime.tenant.tenant_audit import TenantAuditLogger

__all__ = [
    # 枚举
    "TenantStatus",
    "IsolationMode",
    "ResourceType",
    "AuditEventType",
    "QuotaStatus",
    "CrossTenantPolicy",
    # 数据模型
    "TenantQuota",
    "ResourceQuota",
    "TenantConfig",
    "Tenant",
    "TenantMember",
    "TenantAuditRecord",
    "AuditQuery",
    "QuotaCheckResult",
    "TenantStats",
    "TenantFilter",
    # 核心类
    "TenantManager",
    "ResourceQuotaManager",
    "DataIsolator",
    "IsolationPolicy",
    "TenantAuditLogger",
]
