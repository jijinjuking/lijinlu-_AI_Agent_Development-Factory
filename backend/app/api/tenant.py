"""W33-34 Multi-Tenant — API 路由

租户管理 REST API，挂载到 /api/v1/tenants。
"""

from fastapi import APIRouter, HTTPException, Query

from app.runtime.tenant import (
    AuditEventType,
    AuditQuery,
    CrossTenantPolicy,
    DataIsolator,
    IsolationMode,
    IsolationPolicy,
    QuotaStatus,
    ResourceQuotaManager,
    ResourceType,
    TenantAuditLogger,
    TenantConfig,
    TenantManager,
    TenantStatus,
)

router = APIRouter(prefix="/tenants", tags=["Tenants"])

# ── 模块级单例 ──────────────────────────────

_tm = TenantManager()
_quota = ResourceQuotaManager(_tm)
_isolator = DataIsolator(_tm)
_policy = IsolationPolicy(_tm)
_audit = TenantAuditLogger()


# ── 租户 CRUD ───────────────────────────────


@router.post("", status_code=201)
async def create_tenant(config: TenantConfig):
    """创建租户"""
    try:
        tenant = _tm.create_tenant(config)
        _audit.log_tenant_event(tenant.tenant_id, AuditEventType.TENANT_CREATED)
        return tenant
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("")
async def list_tenants(
    status: TenantStatus | None = Query(None),
    isolation_mode: IsolationMode | None = Query(None, alias="isolationMode"),
):
    """列出所有租户"""
    return _tm.list_tenants(status=status, isolation_mode=isolation_mode)


@router.get("/{tenant_id}")
async def get_tenant(tenant_id: str):
    """获取租户详情"""
    tenant = _tm.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.delete("/{tenant_id}")
async def delete_tenant(tenant_id: str):
    """删除租户（需先归档）"""
    try:
        success = _tm.delete_tenant(tenant_id)
        if not success:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return {"deleted": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{tenant_id}")
async def update_tenant(tenant_id: str, updates: dict):
    """更新租户属性"""
    try:
        tenant = _tm.update_tenant(tenant_id, **updates)
        return tenant
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── 生命周期 ─────────────────────────────────


@router.post("/{tenant_id}/activate")
async def activate_tenant(tenant_id: str):
    """激活租户"""
    try:
        tenant = _tm.activate_tenant(tenant_id)
        _audit.log_tenant_event(tenant_id, AuditEventType.TENANT_ACTIVATED)
        return tenant
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{tenant_id}/suspend")
async def suspend_tenant(tenant_id: str, reason: str = ""):
    """暂停租户"""
    try:
        tenant = _tm.suspend_tenant(tenant_id, reason)
        _audit.log_tenant_event(tenant_id, AuditEventType.TENANT_SUSPENDED,
                                 detail={"reason": reason})
        return tenant
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{tenant_id}/archive")
async def archive_tenant(tenant_id: str):
    """归档租户"""
    try:
        tenant = _tm.archive_tenant(tenant_id)
        _audit.log_tenant_event(tenant_id, AuditEventType.TENANT_ARCHIVED)
        return tenant
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 成员管理 ─────────────────────────────────


@router.post("/{tenant_id}/members")
async def add_member(tenant_id: str,
                     user_id: str,
                     role: str = "member",
                     permissions: str = ""):
    """添加租户成员"""
    try:
        perms = [p.strip() for p in permissions.split(",") if p.strip()] if permissions else []
        member = _tm.add_member(tenant_id, user_id, role, perms)
        _audit.log(tenant_id, AuditEventType.MEMBER_JOINED,
                    actor_id=user_id, actor_type="user")
        return member
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{tenant_id}/members/{user_id}")
async def remove_member(tenant_id: str, user_id: str):
    try:
        success = _tm.remove_member(tenant_id, user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Member not found")
        _audit.log(tenant_id, AuditEventType.MEMBER_LEFT,
                    actor_id=user_id, actor_type="user")
        return {"removed": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{tenant_id}/members")
async def list_members(tenant_id: str):
    try:
        return _tm.get_tenant_members(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── 配额管理 ─────────────────────────────────


@router.get("/{tenant_id}/quota")
async def get_quota_summary(tenant_id: str):
    """获取配额摘要"""
    summary = _quota.get_quota_summary(tenant_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return summary


@router.post("/{tenant_id}/quota")
async def set_quota(tenant_id: str,
                    resource_type: ResourceType,
                    limit: float,
                    alert_threshold: float = 0.8):
    """设置配额"""
    try:
        _quota.allocate_quota(tenant_id, resource_type, limit, alert_threshold)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{tenant_id}/quota/defaults")
async def allocate_default_quotas(tenant_id: str, tier: str = "standard"):
    """分配默认配额套餐"""
    try:
        _quota.allocate_default_quotas(tenant_id, tier)
        return {"ok": True, "tier": tier}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{tenant_id}/quota/check")
async def check_quota(tenant_id: str,
                      resource_type: ResourceType,
                      requested: float = 1):
    """检查配额"""
    status = _tm.check_quota(tenant_id, resource_type, requested)
    return {"status": status.value}


@router.post("/{tenant_id}/quota/consume")
async def consume_quota(tenant_id: str,
                        resource_type: ResourceType,
                        amount: float = 1):
    """消费配额"""
    try:
        result = _quota.try_consume(tenant_id, resource_type, amount)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{tenant_id}/quota/release")
async def release_quota(tenant_id: str,
                        resource_type: ResourceType,
                        amount: float = 1):
    """释放配额"""
    try:
        _quota.release(tenant_id, resource_type, amount)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── 隔离与策略 ───────────────────────────────


@router.get("/{tenant_id}/isolation")
async def get_isolation_info(tenant_id: str):
    """获取隔离信息"""
    tenant = _tm.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "isolation_mode": tenant.isolation_mode.value,
        "cross_tenant_policy": tenant.cross_tenant_policy.value,
        "allowed_tenant_ids": tenant.allowed_tenant_ids,
        "schema_name": _isolator.get_schema_name(tenant_id)
        if tenant.isolation_mode == IsolationMode.SCHEMA else None,
    }


@router.post("/check-access")
async def check_cross_tenant_access(source_tenant_id: str, target_tenant_id: str):
    """检查跨租户访问"""
    allowed = _policy.check_access(source_tenant_id, target_tenant_id)
    return {"allowed": allowed}


@router.post("/{tenant_id}/grant-access/{target_tenant_id}")
async def grant_access(tenant_id: str, target_tenant_id: str):
    """授权跨租户访问"""
    success = _isolator.grant_cross_tenant_access(tenant_id, target_tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"granted": True}


@router.delete("/{tenant_id}/grant-access/{target_tenant_id}")
async def revoke_access(tenant_id: str, target_tenant_id: str):
    """撤销跨租户访问"""
    success = _isolator.revoke_cross_tenant_access(tenant_id, target_tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"revoked": True}


# ── 审计 ─────────────────────────────────────


@router.get("/{tenant_id}/audit")
async def get_audit_logs(tenant_id: str,
                         limit: int = 100, offset: int = 0,
                         event_type: AuditEventType | None = None):
    """获取审计日志"""
    query = AuditQuery(
        tenant_id=tenant_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    return _audit.query(query)


@router.get("/{tenant_id}/audit/timeline")
async def get_audit_timeline(tenant_id: str, limit: int = 50):
    """获取审计时间线"""
    return _audit.get_tenant_timeline(tenant_id, limit)


@router.get("/{tenant_id}/audit/violations")
async def get_violations(tenant_id: str, limit: int = 100):
    """获取违规记录"""
    return _audit.get_violations(tenant_id, limit)


# ── 统计 ─────────────────────────────────────


@router.get("/stats")
async def get_global_stats():
    """全局统计"""
    return {
        "total_tenants": _tm.tenant_count,
        "active_tenants": len(_tm.list_tenants(status=TenantStatus.ACTIVE)),
        "suspended_tenants": len(_tm.list_tenants(status=TenantStatus.SUSPENDED)),
        "audit": _audit.get_stats(),
    }


@router.get("/{tenant_id}/stats")
async def get_tenant_stats(tenant_id: str):
    """租户统计"""
    try:
        return _tm.get_tenant_stats(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
