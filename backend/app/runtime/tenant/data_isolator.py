"""W33-34 Multi-Tenant — 数据隔离器

实现不同隔离模式下的数据访问控制：Schema / Row-Level / Hybrid / Shared。
"""

from __future__ import annotations

import logging
from typing import Any

from .models import IsolationMode, TenantFilter, CrossTenantPolicy

logger = logging.getLogger(__name__)


class DataIsolator:
    """数据隔离器 — 根据隔离模式控制数据访问"""

    def __init__(self, tenant_manager):
        from .tenant_manager import TenantManager
        self._tm: TenantManager = tenant_manager

    # ── 过滤器 ────────────────────────────────

    def get_filter(self, tenant_id: str) -> TenantFilter:
        """获取租户数据过滤器"""
        return self._tm.create_filter(tenant_id)

    def get_isolation_mode(self, tenant_id: str) -> IsolationMode:
        """获取租户隔离模式"""
        tenant = self._tm.get_tenant(tenant_id)
        if not tenant:
            return IsolationMode.ROW_LEVEL
        return tenant.isolation_mode

    # ── 数据访问控制 ──────────────────────────

    def filter_query(self, tenant_id: str,
                     query_params: dict[str, Any]) -> dict[str, Any]:
        """对查询参数注入租户隔离过滤"""
        mode = self.get_isolation_mode(tenant_id)

        if mode == IsolationMode.SHARED:
            return query_params  # 共享模式不过滤

        if mode.requires_tenant_filter:
            query_params = dict(query_params)
            query_params["tenant_id"] = tenant_id

        return query_params

    def filter_results(self, tenant_id: str,
                       results: list[dict[str, Any]],
                       tenant_field: str = "tenant_id") -> list[dict[str, Any]]:
        """对查询结果进行租户过滤（应用层保障）"""
        mode = self.get_isolation_mode(tenant_id)

        if mode in (IsolationMode.SHARED, IsolationMode.SCHEMA):
            return results  # Schema 隔离在数据库层已保证，共享模式不过滤

        # Row-Level: 二次过滤保障
        return [r for r in results if r.get(tenant_field) == tenant_id]

    def can_read(self, tenant_id: str, data_tenant_id: str) -> bool:
        """检查租户是否可以读取特定租户的数据"""
        if tenant_id == data_tenant_id:
            return True
        return self._tm.check_cross_tenant_access(tenant_id, data_tenant_id)

    def can_read_all(self, tenant_id: str) -> bool:
        """检查租户是否有全局读权限"""
        mode = self.get_isolation_mode(tenant_id)
        return mode == IsolationMode.SHARED

    def can_write(self, tenant_id: str, data_tenant_id: str) -> bool:
        """检查租户是否可以写入特定租户的数据"""
        return tenant_id == data_tenant_id

    # ── Schema 管理 ───────────────────────────

    def get_schema_name(self, tenant_id: str) -> str:
        """获取租户对应的 Schema 名称"""
        tenant = self._tm.get_tenant(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant '{tenant_id}' not found")
        return f"tenant_{tenant.slug}"

    def list_schemas(self) -> list[str]:
        """列出所有独立 Schema"""
        return [
            f"tenant_{t.slug}"
            for t in self._tm._tenants.values()
            if t.isolation_mode == IsolationMode.SCHEMA
        ]

    # ── 跨租户操作 ────────────────────────────

    def authorize_cross_tenant(self, source_tenant_id: str,
                               target_tenant_id: str,
                               operation: str = "read") -> bool:
        """授权跨租户操作"""
        if source_tenant_id == target_tenant_id:
            return True
        if operation not in ("read", "write"):
            return False
        if operation == "write":
            return False  # 跨租户写操作禁止

        return self._tm.check_cross_tenant_access(source_tenant_id, target_tenant_id)

    def grant_cross_tenant_access(self, source_tenant_id: str,
                                  target_tenant_id: str) -> bool:
        """为租户添加跨租户访问白名单"""
        tenant = self._tm.get_tenant(source_tenant_id)
        if not tenant:
            return False
        if target_tenant_id not in tenant.allowed_tenant_ids:
            tenant.allowed_tenant_ids = tenant.allowed_tenant_ids + [target_tenant_id]
        # 自动切换为 ALLOW_LIST 模式
        if tenant.cross_tenant_policy == CrossTenantPolicy.BLOCK_ALL:
            tenant.cross_tenant_policy = CrossTenantPolicy.ALLOW_LIST
        return True

    def revoke_cross_tenant_access(self, source_tenant_id: str,
                                   target_tenant_id: str) -> bool:
        """撤销跨租户访问"""
        tenant = self._tm.get_tenant(source_tenant_id)
        if not tenant:
            return False
        if target_tenant_id in tenant.allowed_tenant_ids:
            tenant.allowed_tenant_ids = [
                tid for tid in tenant.allowed_tenant_ids
                if tid != target_tenant_id
            ]
        return True
