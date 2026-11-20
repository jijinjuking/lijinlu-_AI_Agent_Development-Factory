"""
W25-26: K8s Job Scheduler — REST API 端点

提供 K8s 集群管理、Job 提交/查询/取消、模板管理 的 HTTP 接口。
挂载到 /api/v1/k8s
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.runtime.k8s_scheduler import (
    K8sJobConfig,
    K8sJobManager,
    K8sJobRecord,
    K8sJobStatus,
    K8sJobType,
    K8sScheduler,
    LocalK8sClient,
)

router = APIRouter()

# ─── 依赖注入 ────────────────────────────────────────────────────────────────

_k8s_scheduler: K8sScheduler | None = None


async def _get_k8s_scheduler() -> K8sScheduler:
    global _k8s_scheduler
    if _k8s_scheduler is None:
        client = LocalK8sClient()
        job_mgr = K8sJobManager(k8s_client=client)
        _k8s_scheduler = K8sScheduler(
            k8s_client=client,
            job_manager=job_mgr,
        )
        await _k8s_scheduler.initialize()
    return _k8s_scheduler


# ─── Job 端点 ────────────────────────────────────────────────────────────────


@router.post("/jobs", status_code=201)
async def create_job(
    payload: dict[str, Any],
    k8s: K8sScheduler = Depends(_get_k8s_scheduler),
) -> dict[str, Any]:
    """提交 K8s Job（支持自定义配置或使用模板）"""
    template_name = payload.get("template", "langgraph_worker")
    task_id = payload.get("task_id", "")

    if "config" in payload:
        # 自定义配置
        config_dict = payload["config"]
        config = K8sJobConfig(
            job_name=config_dict.get("job_name", f"custom-{task_id[:8]}"),
            image=config_dict.get("image", "ai-runtime-os/backend:latest"),
            command=config_dict.get("command", []),
            env_vars=config_dict.get("env_vars", {}),
            namespace=config_dict.get("namespace", "ai-runtime-os"),
        )
        record = await k8s.submit_custom_job(config, task_id)
    else:
        record = await k8s.submit_task_as_job(
            task_id=task_id,
            capability=payload.get("capability", ""),
            template_name=template_name,
            extra_env=payload.get("env_vars"),
        )

    return record.to_dict()


@router.get("/jobs")
async def list_jobs(
    status: str = Query("", description="按状态过滤"),
    k8s: K8sScheduler = Depends(_get_k8s_scheduler),
) -> list[dict[str, Any]]:
    """列出所有 K8s Job"""
    return await k8s.list_all_jobs(status_filter=status)


@router.get("/jobs/stats")
async def get_job_stats(
    k8s: K8sScheduler = Depends(_get_k8s_scheduler),
) -> dict[str, int]:
    """获取 Job 统计信息"""
    return await k8s.get_job_stats()


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    wait: bool = Query(False, description="是否等待 Job 完成"),
    timeout: float = Query(3600, description="等待超时秒数"),
    k8s: K8sScheduler = Depends(_get_k8s_scheduler),
) -> dict[str, Any]:
    """获取单个 Job 详情"""
    record = await k8s.get_job_result(job_id, wait=wait, timeout=timeout)
    if not record:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return record.to_dict()


@router.get("/jobs/{job_id}/logs")
async def get_job_logs(
    job_id: str,
    tail_lines: int = Query(100, ge=1, le=10000),
    k8s: K8sScheduler = Depends(_get_k8s_scheduler),
) -> dict[str, Any]:
    """获取 Job 日志"""
    logs = await k8s.get_job_logs(job_id, tail_lines=tail_lines)
    return {"job_id": job_id, "logs": logs, "lines": len(logs.splitlines()) if logs else 0}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    k8s: K8sScheduler = Depends(_get_k8s_scheduler),
) -> dict[str, Any]:
    """取消 Job"""
    success = await k8s.cancel_task_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found or already terminal")
    return {"job_id": job_id, "status": "cancelled"}


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    k8s: K8sScheduler = Depends(_get_k8s_scheduler),
) -> dict[str, Any]:
    """删除 Job"""
    success = await k8s.delete_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {"job_id": job_id, "deleted": True}


@router.post("/jobs/batch")
async def batch_submit_jobs(
    payload: dict[str, Any],
    k8s: K8sScheduler = Depends(_get_k8s_scheduler),
) -> dict[str, Any]:
    """批量提交 K8s Job"""
    tasks: list[dict[str, Any]] = payload.get("tasks", [])
    if not tasks:
        raise HTTPException(status_code=400, detail="tasks list is required")

    template = payload.get("template", "langgraph_worker")
    max_concurrent = payload.get("max_concurrent", 10)

    records = await k8s.batch_submit(
        tasks=tasks,
        template_name=template,
        max_concurrent=max_concurrent,
    )
    return {
        "submitted": len(records),
        "jobs": [r.to_dict() for r in records],
    }


# ─── 集群端点 ────────────────────────────────────────────────────────────────


@router.get("/cluster")
async def get_cluster_info(
    k8s: K8sScheduler = Depends(_get_k8s_scheduler),
) -> dict[str, Any]:
    """获取 K8s 集群概览"""
    info = await k8s.get_cluster_info()
    return info.to_dict()


@router.get("/nodes")
async def list_nodes(
    k8s: K8sScheduler = Depends(_get_k8s_scheduler),
) -> list[dict[str, Any]]:
    """列出集群节点"""
    nodes = await k8s.get_nodes()
    return [n.to_dict() for n in nodes]


# ─── 模板端点 ────────────────────────────────────────────────────────────────


@router.get("/templates")
async def list_templates(
    k8s: K8sScheduler = Depends(_get_k8s_scheduler),
) -> list[dict[str, Any]]:
    """获取所有 Job 模板"""
    return k8s.get_templates()


# ─── 清理端点 ────────────────────────────────────────────────────────────────


@router.post("/cleanup")
async def cleanup_jobs(
    max_age_hours: int = Query(24, ge=1, le=720),
    k8s: K8sScheduler = Depends(_get_k8s_scheduler),
) -> dict[str, Any]:
    """清理过期 Job"""
    removed = await k8s.cleanup_jobs(max_age_hours)
    return {"removed": removed, "max_age_hours": max_age_hours}


# ─── 健康检查 ────────────────────────────────────────────────────────────────


@router.get("/health")
async def k8s_health(
    k8s: K8sScheduler = Depends(_get_k8s_scheduler),
) -> dict[str, Any]:
    """K8s 调度器健康检查"""
    cluster = await k8s.get_cluster_info()
    stats = await k8s.get_job_stats()
    return {
        "status": "healthy",
        "cluster_ready": cluster.ready_nodes > 0,
        "active_jobs": stats.get("active", 0),
        "max_concurrent": stats.get("max_concurrent", 0),
        "nodes": cluster.node_count,
        "ready_nodes": cluster.ready_nodes,
    }
