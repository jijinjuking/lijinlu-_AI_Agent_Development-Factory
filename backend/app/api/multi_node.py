"""
W27-28: Multi-Node Scheduling — REST API 端点

提供集群节点管理、拓扑查询、跨节点任务调度的 HTTP 接口。
挂载到 /api/v1/multi-node
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.runtime.multi_node import (
    MultiNodeScheduler,
    NodeInfo,
    NodeStatus,
    RoutingStrategy,
)

router = APIRouter()

# ─── 依赖注入 ────────────────────────────────────────────────────────────────

_scheduler: MultiNodeScheduler | None = None


async def _get_scheduler() -> MultiNodeScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = MultiNodeScheduler(
            node_name="api-server",
            node_host="127.0.0.1",
            node_port=8002,
            capabilities=["langgraph_worker", "code_generation", "data_analysis"],
            max_tasks=100,
        )
        await _scheduler.start()
    return _scheduler


# ─── 集群拓扑 ────────────────────────────────────────────────────────────────


@router.get("/topology")
async def get_cluster_topology(
    scheduler: MultiNodeScheduler = Depends(_get_scheduler),
) -> dict[str, Any]:
    """获取集群拓扑信息"""
    return await scheduler.get_cluster_topology()


# ─── 节点管理 ────────────────────────────────────────────────────────────────


@router.get("/nodes")
async def list_nodes(
    status: str = Query("", description="按状态过滤: online/offline/degraded"),
    scheduler: MultiNodeScheduler = Depends(_get_scheduler),
) -> list[dict[str, Any]]:
    """列出所有对等节点"""
    return await scheduler.list_peers(status_filter=status)


@router.get("/nodes/{node_id}")
async def get_node(
    node_id: str,
    scheduler: MultiNodeScheduler = Depends(_get_scheduler),
) -> dict[str, Any]:
    """获取节点详情"""
    node = await scheduler.get_node_detail(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    return node


@router.post("/nodes/register", status_code=201)
async def register_peer(
    payload: dict[str, Any],
    scheduler: MultiNodeScheduler = Depends(_get_scheduler),
) -> dict[str, Any]:
    """注册对等节点"""
    peer = NodeInfo(
        node_name=payload.get("node_name", ""),
        host=payload.get("host", "127.0.0.1"),
        port=payload.get("port", 8000),
        capabilities=payload.get("capabilities", []),
        max_tasks=payload.get("max_tasks", 100),
        region=payload.get("region", "default"),
        zone=payload.get("zone", "default"),
        weight=payload.get("weight", 1.0),
    )
    registered = await scheduler.register_peer(peer)
    return registered.to_dict()


@router.post("/nodes/{node_id}/deregister")
async def deregister_peer(
    node_id: str,
    scheduler: MultiNodeScheduler = Depends(_get_scheduler),
) -> dict[str, Any]:
    """注销对等节点"""
    success = await scheduler.deregister_peer(node_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    return {"node_id": node_id, "status": "deregistered"}


@router.post("/nodes/{node_id}/drain")
async def set_node_draining(
    node_id: str,
    payload: dict[str, Any],
    scheduler: MultiNodeScheduler = Depends(_get_scheduler),
) -> dict[str, Any]:
    """设置节点排空状态"""
    draining = payload.get("draining", True)
    success = await scheduler.set_node_draining(node_id, draining)
    if not success:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    status = "draining" if draining else "online"
    return {"node_id": node_id, "status": status}


@router.get("/nodes/{node_id}/tasks")
async def get_node_tasks(
    node_id: str,
    status: str = Query("", description="按任务状态过滤"),
    scheduler: MultiNodeScheduler = Depends(_get_scheduler),
) -> list[dict[str, Any]]:
    """获取节点上的任务列表"""
    # 先验证节点存在
    node = await scheduler.get_node_detail(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    return await scheduler.get_node_tasks(node_id, status=status)


@router.post("/nodes/heartbeat")
async def send_heartbeat(
    scheduler: MultiNodeScheduler = Depends(_get_scheduler),
) -> dict[str, Any]:
    """发送本节点心跳"""
    heartbeat = await scheduler.send_heartbeat()
    return heartbeat.to_dict()


# ─── 任务调度 ────────────────────────────────────────────────────────────────


@router.post("/schedule")
async def schedule_task(
    payload: dict[str, Any],
    scheduler: MultiNodeScheduler = Depends(_get_scheduler),
) -> dict[str, Any]:
    """调度单个任务到最佳节点"""
    task_id = payload.get("task_id", "")
    capability = payload.get("capability", "")
    workflow_payload = payload.get("workflow_payload") or {}
    strategy_str = payload.get("strategy", "")

    strategy = None
    if strategy_str:
        try:
            strategy = RoutingStrategy(strategy_str)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid strategy: {strategy_str}. "
                       f"Options: {[s.value for s in RoutingStrategy]}",
            )

    decision = await scheduler.schedule_task(
        task_id=task_id,
        capability=capability,
        workflow_payload=workflow_payload,
        strategy=strategy,
        region=payload.get("region", ""),
    )

    if decision is None:
        raise HTTPException(
            status_code=503,
            detail="No available node to handle this task",
        )

    return {
        "task_id": task_id,
        "routing": decision.to_dict(),
    }


@router.post("/schedule/batch")
async def schedule_batch(
    payload: dict[str, Any],
    scheduler: MultiNodeScheduler = Depends(_get_scheduler),
) -> dict[str, Any]:
    """批量调度任务"""
    tasks: list[dict[str, Any]] = payload.get("tasks", [])
    if not tasks:
        raise HTTPException(status_code=400, detail="tasks list is required")

    capability = payload.get("capability", "")
    strategy_str = payload.get("strategy", "")
    strategy = None
    if strategy_str:
        try:
            strategy = RoutingStrategy(strategy_str)
        except ValueError:
            pass

    decisions = await scheduler.schedule_batch(
        tasks=tasks,
        capability=capability,
        strategy=strategy,
    )

    return {
        "total": len(tasks),
        "dispatched": sum(1 for _, d in decisions if d is not None),
        "failed": sum(1 for _, d in decisions if d is None),
        "results": [
            {"task_id": tid, "routing": d.to_dict() if d else None}
            for tid, d in decisions
        ],
    }


@router.post("/tasks/{task_id}/complete")
async def complete_task(
    task_id: str,
    payload: dict[str, Any] | None = None,
    scheduler: MultiNodeScheduler = Depends(_get_scheduler),
) -> dict[str, Any]:
    """标记远程任务完成"""
    result = payload or {}
    success = await scheduler.complete_task(task_id, result)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return {"task_id": task_id, "status": "completed"}


# ─── 统计 ────────────────────────────────────────────────────────────────────


@router.get("/stats")
async def get_stats(
    scheduler: MultiNodeScheduler = Depends(_get_scheduler),
) -> dict[str, Any]:
    """获取多节点调度统计"""
    topology = await scheduler.get_cluster_topology()
    return {
        "this_node": topology["this_node"]["node_name"],
        "peer_count": len(topology["peers"]),
        "active_local_tasks": topology["active_local_tasks"],
        "active_remote_tasks": topology["active_remote_tasks"],
        "cluster_stats": topology["stats"],
        "routing_strategy": topology["routing_strategy"],
    }


# ─── 健康检查 ────────────────────────────────────────────────────────────────


@router.get("/health")
async def multi_node_health(
    scheduler: MultiNodeScheduler = Depends(_get_scheduler),
) -> dict[str, Any]:
    """多节点调度器健康检查"""
    topology = await scheduler.get_cluster_topology()
    stats = topology["stats"]
    return {
        "status": "healthy",
        "this_node": topology["this_node"]["node_name"],
        "cluster_nodes": stats["total_nodes"],
        "online_nodes": stats["online_nodes"],
        "cluster_avg_load": stats["avg_load_ratio"],
    }
