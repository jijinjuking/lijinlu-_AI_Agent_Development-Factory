"""W33-34 Multi-Tenant — 隔离策略引擎

租户间隔离策略：跨租户通信控制、资源隔离级别、安全边界执行。
"""

from __future__ import annotations

import logging
from typing import Any

from .models import (
    AuditEventType,
    CrossTenantPolicy,
    IsolationMode,
    QuotaCheckResult,
    QuotaStatus,
    ResourceType,
    TenantAuditRecord,
)

logger = logging.getLogger(__name__)


class IsolationPolicy:
    """隔离策略引擎 — 租户间隔离与通信控制"""

    def __init__(self, tenant_manager):
        from .tenant_manager import TenantManager
        self._tm: TenantManager = tenant_manager

    # ── 访问控制 ──────────────────────────────

    def check_access(self, source_tenant_id: str,
                     target_tenant_id: str) -> bool:
        """检查租户间访问是否被允许"""
        return self._tm.check_cross_tenant_access(source_tenant_id, target_tenant_id)

    def check_access_with_audit(self, source_tenant_id: str,
                                target_tenant_id: str,
                                actor_id: str = "",
                                reason: str = "") -> bool:
        """检查跨租户访问 + 记录审计"""
        allowed = self.check_access(source_tenant_id, target_tenant_id)
        if not allowed:
            logger.warning(
                "Cross-tenant access denied: %s → %s (actor: %s, reason: %s)",
                source_tenant_id, target_tenant_id, actor_id, reason,
            )
        return allowed

    def get_default_cross_tenant_policy(self) -> CrossTenantPolicy:
        """系统默认跨租户策略"""
        return CrossTenantPolicy.BLOCK_ALL

    # ── 隔离级别 ──────────────────────────────

    def get_effective_isolation_level(self, tenant_id: str) -> IsolationMode:
        """获取租户的有效隔离级别"""
        tenant = self._tm.get_tenant(tenant_id)
        if not tenant:
            return IsolationMode.ROW_LEVEL
        return tenant.isolation_mode

    def recommend_isolation_mode(self, tenant_config: dict[str, Any]) -> IsolationMode:
        """根据租户配置推荐隔离模式"""
        sensitivity = tenant_config.get("data_sensitivity", "low")

        if sensitivity == "high":
            return IsolationMode.SCHEMA
        elif sensitivity == "medium":
            return IsolationMode.HYBRID
        else:
            return IsolationMode.ROW_LEVEL

    def validate_isolation_mode(self, tenant_id: str,
                                target_mode: IsolationMode) -> bool:
        """验证切换隔离模式是否安全"""
        current = self.get_effective_isolation_level(tenant_id)

        # 降级检查：不允许从高隔离降到低隔离
        mode_rank = {
            IsolationMode.SCHEMA: 3,
            IsolationMode.HYBRID: 2,
            IsolationMode.ROW_LEVEL: 1,
            IsolationMode.SHARED: 0,
        }

        if mode_rank.get(target_mode, 0) < mode_rank.get(current, 0):
            logger.warning(
                "Isolation downgrade attempt for tenant %s: %s → %s",
                tenant_id, current.value, target_mode.value,
            )
            return False

        return True

    # ── 策略规则 ──────────────────────────────

    def evaluate_tenant_rules(self, tenant_id: str,
                              action: str, resource: str,
                              context: dict[str, Any] | None = None) -> bool:
        """评估租户级策略规则"""
        tenant = self._tm.get_tenant(tenant_id)
        if not tenant:
            return False
        if not tenant.status.is_operational:
            return False

        context = context or {}

        # 全局资源访问控制
        if action == "use_shared_model" and resource not in ("gpt-4", "claude-3"):
            return True
        if action == "create_api_key":
            return tenant.status.is_operational
        if action == "delete_data":
            return True  # 租户可以删除自己的数据
        if action == "cross_tenant_invoke":
            target = context.get("target_tenant_id", "")
            return self.check_access(tenant_id, target)

        return True

    # ── 批量验证 ──────────────────────────────

    def validate_tenant_isolation(self, tenant_ids: list[str]) -> dict[str, bool]:
        """批量验证租户间隔离"""
        result = {}
        for i, t1 in enumerate(tenant_ids):
            for t2 in tenant_ids[i + 1:]:
                key = f"{t1}↔{t2}"
                result[key] = not self.check_access(t1, t2)  # 默认应 block
        return result
