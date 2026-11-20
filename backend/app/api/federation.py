"""W31-32 Runtime Federation — REST API

联邦成员管理、跨集群任务分发、状态同步、统计查询。
挂载到 /api/v1/federation
"""

from fastapi import APIRouter, HTTPException, Query

from app.runtime.federation import (
    DispatchPolicy,
    DispatchRequest,
    FederationGateway,
    FederationPolicyConfig,
    FederationPolicyEngine,
    FederationRegistry,
    JoinRequest,
    MemberHeartbeatRequest,
    MemberStatus,
    StateSyncEngine,
    SyncScope,
    SyncStatus,
)

router = APIRouter(prefix="/federation", tags=["Federation"])

# ── 模块级单例 ──────────────────────────────
_registry = FederationRegistry()
_policy = FederationPolicyEngine()
_gateway = FederationGateway(_registry, _policy)
_sync_engine = StateSyncEngine(_registry, _policy)

# 启动后台任务
_registry.start_cleanup()
_gateway.start_monitor()


# ── 成员管理 ──────────────────────────────────


@router.post("/members/join")
async def join_federation(request: JoinRequest):
    """成员加入联邦"""
    try:
        member = await _registry.join(request)
        return {"success": True, "member": member}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/members/{member_id}/leave")
async def leave_federation(member_id: str, graceful: bool = True):
    """成员离开联邦"""
    member = await _registry.leave(member_id, graceful=graceful)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"success": True, "member": member}


@router.post("/members/heartbeat")
async def member_heartbeat(request: MemberHeartbeatRequest):
    """成员心跳"""
    member = await _registry.heartbeat(request)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"success": True, "member": member}


@router.delete("/members/{member_id}")
async def deregister_member(member_id: str):
    """强制移除成员"""
    member = _registry.deregister(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"success": True, "member": member}


@router.get("/members")
async def list_members(
    status: str | None = Query(None, alias="status"),
    cluster_id: str = Query("", alias="clusterId"),
    region: str = Query(""),
    capability: str = Query(""),
):
    """列出成员"""
    member_status = MemberStatus(status) if status else None
    members = _registry.list_members(
        status=member_status, cluster_id=cluster_id,
        region=region, capability=capability)
    return {"members": members, "total": len(members)}


@router.get("/members/{member_id}")
async def get_member(member_id: str):
    """获取成员详情"""
    member = _registry.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


@router.get("/members/available")
async def get_available_members(
    capability: str = Query(""),
    region: str = Query(""),
):
    """获取可用成员（可接新任务）"""
    members = _registry.get_available_members(capability=capability, region=region)
    return {"members": members, "total": len(members)}


# ── 集群管理 ──────────────────────────────────


@router.get("/clusters")
async def list_clusters():
    """列出所有集群"""
    clusters = _registry.list_clusters()
    return {"clusters": clusters, "total": len(clusters)}


@router.get("/clusters/{cluster_id}")
async def get_cluster(cluster_id: str):
    """获取集群详情"""
    cluster = _registry.get_cluster(cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return cluster


@router.post("/clusters/{cluster_id}/elect")
async def elect_leader(cluster_id: str):
    """选举集群 Leader"""
    leader = await _registry.elect_leader(cluster_id)
    if not leader:
        raise HTTPException(status_code=404, detail="No available members in cluster")
    return {"success": True, "leader": leader}


# ── 拓扑 ──────────────────────────────────────


@router.get("/topology")
async def get_topology():
    """获取联邦拓扑"""
    return _registry.get_topology()


# ── 任务分发 ──────────────────────────────────


@router.post("/dispatch")
async def dispatch_task(request: DispatchRequest,
                        source_member_id: str = Query(""),
                        source_cluster_id: str = Query("")):
    """分发跨集群任务"""
    result = await _gateway.dispatch(
        request,
        source_member_id=source_member_id,
        source_cluster_id=source_cluster_id)
    if not result.accepted:
        raise HTTPException(status_code=503, detail=result.reason)
    return result


@router.post("/dispatch/batch")
async def dispatch_batch(requests: list[DispatchRequest],
                         source_member_id: str = Query(""),
                         source_cluster_id: str = Query("")):
    """批量分发任务"""
    results = await _gateway.dispatch_batch(
        requests, source_member_id, source_cluster_id)
    return {"results": results, "total": len(results)}


@router.get("/tasks")
async def list_tasks(
    status: str = Query(""),
    target_cluster_id: str = Query(""),
    target_member_id: str = Query(""),
):
    """列出跨集群任务"""
    tasks = _gateway.list_tasks(
        status=status,
        target_cluster_id=target_cluster_id,
        target_member_id=target_member_id)
    return {"tasks": tasks, "total": len(tasks)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """获取跨集群任务"""
    task = _gateway.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """取消任务"""
    success = await _gateway.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found or already terminal")
    return {"success": True}


@router.post("/tasks/{task_id}/complete")
async def complete_task(task_id: str,
                        success: bool = True,
                        result: dict | None = None,
                        error_message: str = ""):
    """标记任务完成"""
    task = await _gateway.complete_task(
        task_id, success=success, result=result, error_message=error_message)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/tasks/{task_id}/wait")
async def wait_for_task(task_id: str, timeout: float = 60):
    """等待任务完成"""
    task = await _gateway.wait_for_task(task_id, timeout=timeout)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ── 状态同步 ──────────────────────────────────


@router.post("/sync")
async def sync_to_target(
    target_member_id: str = Query(...),
    source_member_id: str = Query(...),
    scope: str | None = Query(None),
    state_keys: list[str] | None = None,
    artifact_ids: list[str] | None = None,
    checkpoint_ids: list[str] | None = None,
):
    """向目标同步数据"""
    sync_scope = SyncScope(scope) if scope else None
    record = await _sync_engine.sync_to(
        target_member_id=target_member_id,
        source_member_id=source_member_id,
        scope=sync_scope,
        state_keys=state_keys,
        artifact_ids=artifact_ids,
        checkpoint_ids=checkpoint_ids)
    return record


@router.post("/sync/broadcast")
async def sync_to_all(
    source_member_id: str = Query(...),
    scope: str | None = Query(None),
):
    """向所有成员广播同步"""
    sync_scope = SyncScope(scope) if scope else None
    records = await _sync_engine.sync_to_all(source_member_id, scope=sync_scope)
    return {"records": records, "total": len(records)}


@router.post("/sync/bidirectional")
async def sync_bidirectional(
    member_a_id: str = Query(...),
    member_b_id: str = Query(...),
):
    """双向同步"""
    records = await _sync_engine.sync_bidirectional(member_a_id, member_b_id)
    return {"records": records, "total": len(records)}


@router.get("/sync/records")
async def list_sync_records(
    source_member_id: str = Query(""),
    target_member_id: str = Query(""),
    status: str | None = Query(None),
):
    """列出同步记录"""
    sync_status = SyncStatus(status) if status else None
    records = _sync_engine.list_records(
        source_member_id=source_member_id,
        target_member_id=target_member_id,
        status=sync_status)
    return {"records": records, "total": len(records)}


@router.get("/sync/records/{sync_id}")
async def get_sync_record(sync_id: str):
    """获取同步记录"""
    record = _sync_engine.get_record(sync_id)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


@router.post("/sync/records/{sync_id}/resolve")
async def resolve_sync_conflict(sync_id: str, resolution: str = "keep_source"):
    """解决同步冲突"""
    record = await _sync_engine.resolve_conflict(sync_id, resolution)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


# ── 同步状态（供前端 FederationPage 使用） ─────────────────────

@router.get("/sync-status")
async def get_sync_statuses():
    """获取成员同步状态（简化实现）"""
    members = _registry.list_members()
    statuses = []
    for m in members:
        statuses.append({
            "member_id": m.member_id,
            "last_sync": m.last_seen,
            "sync_status": "idle",
            "pending_items": 0,
        })
    return statuses


# ── 策略配置 ──────────────────────────────────


@router.get("/policy")
async def get_policy():
    """获取当前策略配置"""
    return _policy.get_config()


@router.put("/policy")
async def update_policy(**kwargs):
    """更新策略配置"""
    return _policy.update_config(**kwargs)


# ── 统计 ──────────────────────────────────────


@router.get("/stats")
async def get_federation_stats():
    """获取联邦统计"""
    return {
        "federation": _registry.get_stats(),
        "gateway": _gateway.get_stats(),
        "sync": _sync_engine.get_stats(),
    }


@router.get("/stats/members")
async def get_member_stats():
    """获取联邦成员统计"""
    return _registry.get_stats()


@router.get("/stats/gateway")
async def get_gateway_stats():
    """获取网关统计"""
    return _gateway.get_stats()


@router.get("/stats/sync")
async def get_sync_stats():
    """获取同步统计"""
    return _sync_engine.get_stats()


# ── 健康检查 ──────────────────────────────────


@router.get("/health")
async def federation_health():
    """联邦健康检查"""
    stats = _registry.get_stats()
    return {
        "healthy": stats.active_members > 0,
        "active_members": stats.active_members,
        "total_members": stats.total_members,
        "clusters": stats.total_clusters,
        "overall_load": stats.overall_load,
    }


# ── 注册 Dispatcher ──────────────────────────


@router.post("/dispatchers/{capability}")
async def register_dispatcher(capability: str):
    """注册能力分发器（简化：仅标记支持）"""
    async def _default_dispatcher(payload: dict) -> dict:
        return {"status": "completed", "capability": capability}

    _gateway.register_dispatcher(capability, _default_dispatcher)
    return {"success": True, "capability": capability}


@router.delete("/dispatchers/{capability}")
async def unregister_dispatcher(capability: str):
    """注销能力分发器"""
    _gateway.unregister_dispatcher(capability)
    return {"success": True, "capability": capability}
