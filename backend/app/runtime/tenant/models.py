"""W33-34 Multi-Tenant 隔离 — 数据模型

多租户隔离系统的数据模型：租户、配额、隔离策略、审计。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


# ──────────────────────────────────────────────
# 枚举
# ──────────────────────────────────────────────


class TenantStatus(str, Enum):
    """租户生命周期状态"""

    PENDING = "pending"           # 待审批
    ACTIVE = "active"             # 正常使用
    SUSPENDED = "suspended"       # 暂停（欠费/违规）
    ARCHIVED = "archived"         # 已归档（只读保留）

    @property
    def is_operational(self) -> bool:
        """是否可执行操作"""
        return self == TenantStatus.ACTIVE

    @property
    def can_transition(self) -> bool:
        """是否允许状态流转"""
        return self in (TenantStatus.PENDING, TenantStatus.ACTIVE, TenantStatus.SUSPENDED)


class IsolationMode(str, Enum):
    """数据隔离模式"""

    SCHEMA = "schema"             # Schema 级隔离（独立数据库/Schema）
    ROW_LEVEL = "row_level"       # 行级隔离（tenant_id 过滤）
    HYBRID = "hybrid"             # 混合模式（敏感数据 Schema 隔离，普通数据行级）
    SHARED = "shared"             # 共享模式（内部平台租户）

    @property
    def requires_tenant_filter(self) -> bool:
        """是否需要租户过滤"""
        return self in (IsolationMode.ROW_LEVEL, IsolationMode.HYBRID)


class ResourceType(str, Enum):
    """可配额资源类型"""

    CPU_CORES = "cpu_cores"
    MEMORY_MB = "memory_mb"
    STORAGE_MB = "storage_mb"
    API_CALLS_PER_DAY = "api_calls_per_day"
    MAX_CONCURRENCY = "max_concurrency"
    TOKENS_PER_DAY = "tokens_per_day"
    TASKS_PER_DAY = "tasks_per_day"
    AGENTS_MAX = "agents_max"


class AuditEventType(str, Enum):
    """租户审计事件类型"""

    TENANT_CREATED = "tenant.created"
    TENANT_SUSPENDED = "tenant.suspended"
    TENANT_ACTIVATED = "tenant.activated"
    TENANT_ARCHIVED = "tenant.archived"
    TENANT_DELETED = "tenant.deleted"
    QUOTA_EXCEEDED = "quota.exceeded"
    QUOTA_ADJUSTED = "quota.adjusted"
    RESOURCE_CONSUMED = "resource.consumed"
    RESOURCE_RELEASED = "resource.released"
    MEMBER_JOINED = "member.joined"
    MEMBER_LEFT = "member.left"
    CROSS_TENANT_ACCESS = "cross_tenant.access"
    ISOLATION_VIOLATION = "isolation.violation"
    POLICY_CHANGED = "policy.changed"


class QuotaStatus(str, Enum):
    """配额状态"""

    OK = "ok"
    WARNING = "warning"           # 接近上限 (>80%)
    EXCEEDED = "exceeded"         # 已超过上限


class CrossTenantPolicy(str, Enum):
    """跨租户通信策略"""

    BLOCK_ALL = "block_all"       # 完全禁止
    ALLOW_LIST = "allow_list"     # 白名单模式
    OPEN = "open"                 # 开放模式


# ──────────────────────────────────────────────
# 资源配额
# ──────────────────────────────────────────────


@dataclass
class TenantQuota:
    """单项资源配额定义"""

    resource_type: ResourceType
    limit: float
    used: float = 0.0
    alert_threshold: float = 0.8       # 告警阈值（0-1）
    is_hard_limit: bool = True          # 硬限制（超限即拒绝）vs 软限制（告警不拒绝）

    @property
    def usage_pct(self) -> float:
        """使用百分比"""
        if self.limit <= 0:
            return 0.0
        return self.used / self.limit

    @property
    def status(self) -> QuotaStatus:
        if self.limit <= 0:
            return QuotaStatus.OK
        if self.used > self.limit:
            return QuotaStatus.EXCEEDED
        if self.usage_pct >= self.alert_threshold:
            return QuotaStatus.WARNING
        return QuotaStatus.OK

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit - self.used)


@dataclass
class ResourceQuota:
    """租户资源配额集合"""

    quotas: dict[ResourceType, TenantQuota] = field(default_factory=dict)

    def get(self, resource_type: ResourceType) -> TenantQuota | None:
        return self.quotas.get(resource_type)

    def set_limit(self, resource_type: ResourceType, limit: float,
                  alert_threshold: float = 0.8, is_hard_limit: bool = True):
        if resource_type in self.quotas:
            self.quotas[resource_type].limit = limit
            self.quotas[resource_type].alert_threshold = alert_threshold
            self.quotas[resource_type].is_hard_limit = is_hard_limit
        else:
            self.quotas[resource_type] = TenantQuota(
                resource_type=resource_type,
                limit=limit,
                alert_threshold=alert_threshold,
                is_hard_limit=is_hard_limit,
            )

    def check(self, resource_type: ResourceType,
              requested: float = 1) -> QuotaStatus:
        """检查某项资源是否还有余量"""
        quota = self.quotas.get(resource_type)
        if not quota or quota.limit <= 0:
            return QuotaStatus.OK
        projected = quota.used + requested
        if projected > quota.limit:
            return QuotaStatus.EXCEEDED
        if projected / quota.limit >= quota.alert_threshold:
            return QuotaStatus.WARNING
        return QuotaStatus.OK

    def consume(self, resource_type: ResourceType, amount: float = 1) -> QuotaStatus:
        """消费资源配额"""
        quota = self.quotas.get(resource_type)
        if not quota:
            return QuotaStatus.OK
        quota.used += amount
        return quota.status

    def release(self, resource_type: ResourceType, amount: float = 1):
        """释放资源配额"""
        quota = self.quotas.get(resource_type)
        if quota:
            quota.used = max(0.0, quota.used - amount)

    def to_summary(self) -> dict:
        """配额总览"""
        result = {}
        for rt, q in self.quotas.items():
            result[rt.value] = {
                "limit": q.limit,
                "used": q.used,
                "remaining": q.remaining,
                "usage_pct": round(q.usage_pct * 100, 1),
                "status": q.status.value,
            }
        return result


# ──────────────────────────────────────────────
# 租户配置
# ──────────────────────────────────────────────


@dataclass
class TenantConfig:
    """租户配置"""

    tenant_name: str
    tenant_slug: str                    # URL-safe 标识
    isolation_mode: IsolationMode = IsolationMode.ROW_LEVEL
    cross_tenant_policy: CrossTenantPolicy = CrossTenantPolicy.BLOCK_ALL
    allowed_tenant_ids: list[str] = field(default_factory=list)  # 白名单租户
    tags: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────
# 租户
# ──────────────────────────────────────────────


@dataclass
class Tenant:
    """租户"""

    tenant_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    slug: str = ""
    status: TenantStatus = TenantStatus.PENDING
    isolation_mode: IsolationMode = IsolationMode.ROW_LEVEL
    cross_tenant_policy: CrossTenantPolicy = CrossTenantPolicy.BLOCK_ALL
    allowed_tenant_ids: list[str] = field(default_factory=list)
    quota: ResourceQuota = field(default_factory=ResourceQuota)
    tags: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    activated_at: datetime | None = None
    suspended_at: datetime | None = None
    suspended_reason: str = ""

    @property
    def is_operational(self) -> bool:
        return self.status == TenantStatus.ACTIVE

    @property
    def member_count(self) -> int:
        """成员数量（需外部设置，此处为默认占位）"""
        return getattr(self, "_member_count", 0)


@dataclass
class TenantMember:
    """租户成员"""

    member_id: str = field(default_factory=lambda: str(uuid4()))
    tenant_id: str = ""
    user_id: str = ""
    role: str = "member"               # admin / member / viewer
    permissions: list[str] = field(default_factory=list)
    joined_at: datetime = field(default_factory=datetime.now)
    last_active_at: datetime | None = None


# ──────────────────────────────────────────────
# 审计
# ──────────────────────────────────────────────


@dataclass
class TenantAuditRecord:
    """租户审计记录"""

    record_id: str = field(default_factory=lambda: str(uuid4()))
    tenant_id: str = ""
    event_type: AuditEventType = AuditEventType.TENANT_CREATED
    actor_id: str = ""                  # 操作者（用户/Agent）
    actor_type: str = ""                # "user" / "agent" / "system"
    resource_type: str = ""             # 操作资源
    resource_id: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    error_message: str = ""


@dataclass
class AuditQuery:
    """审计查询条件"""

    tenant_id: str = ""
    event_type: AuditEventType | None = None
    actor_id: str = ""
    resource_type: str = ""
    start_time: datetime | None = None
    end_time: datetime | None = None
    limit: int = 100
    offset: int = 0


# ──────────────────────────────────────────────
# 配额操作结果
# ──────────────────────────────────────────────


@dataclass
class QuotaCheckResult:
    """配额检查结果"""

    allowed: bool = True
    status: QuotaStatus = QuotaStatus.OK
    exceeded_resources: list[ResourceType] = field(default_factory=list)
    warning_resources: list[ResourceType] = field(default_factory=list)
    message: str = ""


@dataclass
class TenantStats:
    """租户统计"""

    tenant_id: str = ""
    tenant_name: str = ""
    total_members: int = 0
    total_tasks: int = 0
    total_api_calls: int = 0
    total_tokens: int = 0
    total_storage_mb: float = 0.0
    quota_summary: dict = field(default_factory=dict)


# ──────────────────────────────────────────────
# 数据隔离过滤
# ──────────────────────────────────────────────


@dataclass
class TenantFilter:
    """数据隔离过滤器 — 用于数据访问层注入"""

    tenant_id: str
    isolation_mode: IsolationMode = IsolationMode.ROW_LEVEL

    def apply_to_query(self, query_params: dict) -> dict:
        """对查询参数注入 tenant_id 过滤"""
        if self.isolation_mode.requires_tenant_filter:
            query_params["tenant_id"] = self.tenant_id
        return query_params

    def can_access_tenant(self, target_tenant_id: str) -> bool:
        """检查是否可以访问其他租户数据"""
        return target_tenant_id == self.tenant_id
