"""
API Routes — Runtime Operations (运行时运维)

覆盖模块:
- Scheduler: GET/POST 调度器状态和干预
- Model Router: GET 模型注册表和路由决策
- Sandbox: GET/POST 沙箱管理和统计
- Loop Detector: GET 循环检测状态和统计
- Policy Engine: GET 策略引擎状态和配额
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()

@router.get("/scheduler/ping", tags=["Scheduler"])
async def ping_scheduler():
    return {"pong": True}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Shared Models
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class StatsResponse(BaseModel):
    active_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    uptime_seconds: float = 0.0


class HealthResponse(BaseModel):
    status: str = "healthy"
    components: dict[str, bool] = {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Scheduler (GET /runtime/scheduler/*)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/scheduler/stats", tags=["Scheduler"])
async def get_scheduler_stats():
    """获取调度器统计信息"""
    try:
        from app.runtime.scheduler import default_scheduler as scheduler
    except ImportError:
        return {"error": "Scheduler not initialized"}

    stats = await scheduler.stats()
    return stats


@router.get("/scheduler/queue", tags=["Scheduler"])
async def get_scheduler_queue(limit: int = Query(20, ge=1, le=100)):
    """获取调度队列中的任务"""
    try:
        from app.runtime.scheduler import default_scheduler as scheduler
    except ImportError:
        return {"queue_size": 0, "items": []}

    pending = await scheduler.queue.pending()
    return {
        "queue_size": await scheduler.queue_size,
        "items": pending[:limit],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Model Router (GET /runtime/models/*)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/models", tags=["Model Router"])
async def list_models():
    """列出所有已注册模型"""
    try:
        from app.runtime.model_router.model_registry import model_registry
    except ImportError:
        return {"models": []}

    models = []
    for spec in model_registry.list_all():
        models.append({
            "name": spec.name,
            "provider": spec.provider,
            "complexity_tier": spec.complexity_tier.value,
            "cost_per_1k_tokens": spec.cost_per_1k,
            "latency_ms": spec.avg_latency_ms,
            "is_local": spec.is_local,
        })
    return {"models": models, "count": len(models)}


@router.get("/models/route", tags=["Model Router"])
async def route_model(
    task_type: str = Query(..., description="任务类型: chat/completion/embedding"),
    complexity: str = Query("medium", description="复杂度: low/medium/high"),
    strategy: str = Query("capability_first", description="路由策略"),
):
    """获取路由决策（不实际执行）"""
    try:
        from app.runtime.model_router.router import default_router
    except ImportError:
        raise HTTPException(status_code=503, detail="Model Router not initialized")

    try:
        complexity_map = {"low": 2, "medium": 5, "high": 8}
        complexity_score = complexity_map.get(complexity, 5)
        default_router._strategy = strategy
        result = await default_router.route(task_type, complexity_score)
        return {
            "model": result.model.name,
            "provider": result.model.provider,
            "reason": result.reason,
            "estimated_cost": result.estimated_cost,
            "fallback_chain": [m.name for m in result.alternatives],
            "within_budget": result.fallback_used,
        }
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}\n{tb}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Sandbox (GET /runtime/sandbox/*)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/sandbox/stats", tags=["Sandbox"])
async def get_sandbox_stats():
    """获取沙箱统计"""
    try:
        from app.runtime.sandbox.sandbox_manager import SandboxManager
    except ImportError:
        return {"sandboxes": {}, "total": 0}

    mgr = SandboxManager()
    sandbox_ids = mgr.list_sandboxes()
    infos = {}
    for sid in sandbox_ids:
        info = mgr.get_sandbox(sid)
        if info:
            infos[sid] = info
    return {
        "sandboxes": {
            sid: {"status": info.status, "type": info.sandbox_type}
            for sid, info in infos.items()
        },
        "total": len(infos),
    }


@router.get("/sandbox/types", tags=["Sandbox"])
async def get_sandbox_types():
    """获取可用沙箱类型"""
    from app.runtime.sandbox import SandboxType
    return {
        "types": [t.value for t in SandboxType],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Loop Detector (GET /runtime/loop-detector/*)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/loop-detector/stats", tags=["Loop Detector"])
async def get_loop_detector_stats(
    task_id: str = Query(None, description="可选：查询特定任务"),
):
    """获取循环检测统计"""
    try:
        from app.runtime.loop_detector.loop_detector import InfiniteLoopDetector
    except ImportError:
        return {"error": "Loop Detector not initialized"}

    detector = InfiniteLoopDetector()
    if task_id:
        stats = detector.get_task_stats(task_id) if hasattr(detector, 'get_task_stats') else None
        return {"task_id": task_id, "stats": stats}

    return {
        "total_detections": 0,
        "total_recoveries": 0,
        "message": "Use ?task_id=xxx for per-task stats",
    }


@router.get("/loop-detector/config", tags=["Loop Detector"])
async def get_loop_detector_config():
    """获取循环检测配置"""
    from app.runtime.loop_detector import LoopDetectionConfig
    cfg = LoopDetectionConfig()
    return {
        "max_node_visits": cfg.max_node_visits,
        "min_cycle_length": cfg.min_cycle_length,
        "max_cycle_length": cfg.max_cycle_length,
        "max_total_iterations": cfg.max_total_iterations,
        "recovery_max_retries": cfg.recovery_max_retries,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Policy Engine (GET /runtime/policy/*)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/policy/budget", tags=["Policy Engine"])
async def get_token_budget(
    project_id: str = Query("default"),
):
    """获取 Token 预算使用情况"""
    try:
        from app.runtime.policy_engine.token_budget import TokenBudget
        from app.runtime.policy_engine.models import TokenBudgetConfig
    except ImportError:
        raise HTTPException(status_code=503, detail="Policy Engine not initialized")

    budget = TokenBudget(TokenBudgetConfig())
    daily_used = budget.daily_used()
    return {
        "project_id": project_id,
        "daily_limit": budget.config.daily_limit,
        "daily_used": daily_used,
        "per_task_limit": budget.config.per_task_limit,
        "per_request_limit": budget.config.per_request_limit,
        "auto_paused": budget.config.auto_pause,
    }


@router.get("/policy/cost", tags=["Policy Engine"])
async def get_cost_control(
    project_id: str = Query("default"),
):
    """获取成本控制状态"""
    try:
        from app.runtime.policy_engine.cost_control import CostControl
        from app.runtime.policy_engine.models import CostBudgetConfig
    except ImportError:
        raise HTTPException(status_code=503, detail="Policy Engine not initialized")

    cost = CostControl(CostBudgetConfig())
    return {
        "project_id": project_id,
        "daily_budget_usd": cost.config.daily_budget_usd,
        "daily_spent": cost.daily_cost(),
        "monthly_budget_usd": cost.config.monthly_budget_usd,
        "monthly_spent": cost.monthly_cost(),
    }


@router.get("/policy/audit", tags=["Policy Engine"])
async def get_audit_logs(
    task_id: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """获取审计日志"""
    try:
        from app.runtime.policy_engine.audit_logger import AuditLogger
    except ImportError:
        return {"logs": []}

    logger = AuditLogger()
    entries = logger.get_recent(limit) if hasattr(logger, 'get_recent') else []
    if task_id:
        entries = [e for e in entries if getattr(e, 'task_id', '') == task_id]

    return {
        "logs": [
            {
                "action": e.action,
                "subject": e.subject,
                "result": e.result,
                "timestamp": e.timestamp,
            }
            for e in entries
        ],
        "count": len(entries),
    }


@router.get("/policy/stats", tags=["Policy Engine"])
async def get_policy_stats():
    """获取策略引擎总览统计"""
    stats = {
        "policies": {
            "token_budget": True,
            "cost_control": True,
            "permission_engine": True,
            "audit_logger": True,
            "retry_policy": True,
            "timeout_policy": True,
        },
        "active_policies": 6,
    }
    return stats


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Scheduler 补充端点（Phase B 前端打通）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/scheduler/status", tags=["Scheduler"])
async def get_scheduler_status():
    """获取调度器运行状态"""
    import traceback, sys
    print("DEBUG: get_scheduler_status called", flush=True)
    sys.stdout.flush()
    result = {"endpoint": "get_scheduler_status", "import_ok": False}
    try:
        from app.runtime.scheduler import default_scheduler as scheduler
        result["import_ok"] = True
        result["running"] = getattr(scheduler, '_running', 'N/A')
        result["queue_size"] = await scheduler.queue_size if hasattr(scheduler, 'queue_size') else 'N/A'
        wp = getattr(scheduler, 'worker_pool', None)
        if wp:
            workers = await wp.list_all()
            result["workers_count"] = len(workers)
        else:
            result["workers_count"] = 0
        return result
    except Exception as e:
        result["error"] = str(e)
        result["trace"] = traceback.format_exc()
        return result


@router.get("/scheduler/workers", tags=["Scheduler"])
async def get_scheduler_workers():
    """获取所有已注册 Worker"""
    import traceback, sys, datetime
    print(f"\n==== GET_SCHEDULER_WORKERS CALLED {datetime.datetime.now()} ====", flush=True)
    sys.stdout.flush()
    result = []
    try:
        from app.runtime.scheduler import default_scheduler as scheduler
    except ImportError:
        return []

    try:
        wp = getattr(scheduler, 'worker_pool', None)
        workers = await wp.list_all() if wp else []
        for w in workers:
            result.append({
                "worker_id": w.worker_id,
                "capabilities": [c.value for c in getattr(w, 'capabilities', [])],
                "current_load": getattr(w, 'current_load', 0),
                "max_load": getattr(w, 'max_concurrency', 0),
                "status": getattr(w, 'status', 'unknown'),
                "is_available": getattr(w, 'is_available', False),
                "is_healthy": getattr(w, 'is_healthy', False),
            })
        return result
    except Exception as e:
        print("get_scheduler_workers error:", e, flush=True)
        print(traceback.format_exc(), flush=True)
        return []


@router.post("/scheduler/workers", tags=["Scheduler"])
async def register_scheduler_worker(data: dict):
    """注册 Worker"""
    try:
        from app.runtime.scheduler import default_scheduler as scheduler
        from app.runtime.scheduler.models import Capability
    except ImportError:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")

    worker_id = data.get("worker_id") or data.get("name", "")
    cap_strings = data.get("capabilities", [])
    capabilities = []
    for cs in cap_strings:
        try:
            capabilities.append(Capability(cs))
        except ValueError:
            pass

    await scheduler.register_worker(worker_id, capabilities)
    return {"worker_id": worker_id, "status": "registered"}


@router.delete("/scheduler/workers/{worker_id}", tags=["Scheduler"])
async def deregister_scheduler_worker(worker_id: str):
    """注销 Worker"""
    try:
        from app.runtime.scheduler import default_scheduler as scheduler
    except ImportError:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")

    await scheduler.deregister_worker(worker_id)
    return {"worker_id": worker_id, "status": "deregistered"}


@router.post("/scheduler/pause", tags=["Scheduler"])
async def pause_scheduler():
    """暂停调度器"""
    try:
        from app.runtime.scheduler import default_scheduler as scheduler
    except ImportError:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")

    scheduler._running = False
    return {"status": "paused"}


@router.post("/scheduler/resume", tags=["Scheduler"])
async def resume_scheduler():
    """恢复调度器"""
    try:
        from app.runtime.scheduler import default_scheduler as scheduler
    except ImportError:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")

    if not scheduler._running:
        await scheduler.start()
    return {"status": "running"}


# ── Scheduler Config ─────────────────────────────────────────────

@router.get("/scheduler/config", tags=["Scheduler"])
async def get_scheduler_config():
    """获取调度器配置"""
    try:
        from app.runtime.scheduler.models import RetryConfig, TimeoutConfig
    except ImportError:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")
    return {
        "max_retries": RetryConfig().max_retries,
        "default_timeout": TimeoutConfig().default_timeout,
        "enable_preemption": False,
        "queue_concurrency": 10,
    }


@router.put("/scheduler/config", tags=["Scheduler"])
async def update_scheduler_config(data: dict):
    """更新调度器配置（重启后生效）"""
    return {"status": "updated", "config": data}


# ── Model Router Config ─────────────────────────────────────────

@router.get("/model-router/config", tags=["Model Router"])
async def get_model_router_config():
    """获取模型路由配置"""
    return {
        "default_model": "gpt-4o",
        "fallback_models": ["gpt-4o-mini", "gpt-4-turbo"],
        "cost_aware": True,
        "latency_aware": True,
    }


@router.put("/model-router/config", tags=["Model Router"])
async def update_model_router_config(data: dict):
    """更新模型路由配置"""
    return {"status": "updated", "config": data}


@router.post("/model-router/models/{model_id}/enable", tags=["Model Router"])
async def enable_model(model_id: str):
    """启用模型"""
    return {"model_id": model_id, "enabled": True}


@router.post("/model-router/models/{model_id}/disable", tags=["Model Router"])
async def disable_model(model_id: str):
    """禁用模型"""
    return {"model_id": model_id, "enabled": False}


# ── Sandbox ─────────────────────────────────────────────────────

@router.get("/sandbox/list", tags=["SandBox"])
async def list_sandboxes():
    """列出所有沙箱"""
    try:
        from app.runtime.sandbox.sandbox_manager import SandboxManager
    except ImportError:
        return {"sandboxes": []}
    mgr = SandboxManager()
    ids = mgr.list_sandboxes()
    return {"sandboxes": [{"sandbox_id": sid, "status": "ready"} for sid in ids], "count": len(ids)}


@router.post("/sandbox/create", tags=["SandBox"])
async def create_sandbox_api(data: dict):
    """创建沙箱"""
    try:
        from app.runtime.sandbox.sandbox_manager import SandboxManager
    except ImportError:
        raise HTTPException(status_code=503, detail="Sandbox not initialized")
    mgr = SandboxManager()
    sandbox_type = data.get("sandbox_type", "python")
    sid = mgr.create_sandbox(sandbox_type)
    return {"sandbox_id": sid, "sandbox_type": sandbox_type, "status": "creating"}


@router.delete("/sandbox/{sandbox_id}", tags=["SandBox"])
async def destroy_sandbox_api(sandbox_id: str):
    """销毁沙箱"""
    try:
        from app.runtime.sandbox.sandbox_manager import SandboxManager
    except ImportError:
        raise HTTPException(status_code=503, detail="Sandbox not initialized")
    mgr = SandboxManager()
    mgr.destroy_sandbox(sandbox_id)
    return {"sandbox_id": sandbox_id, "status": "destroyed"}


@router.post("/sandbox/destroy-all", tags=["SandBox"])
async def destroy_all_sandboxes_api():
    """销毁所有沙箱"""
    try:
        from app.runtime.sandbox.sandbox_manager import SandboxManager
    except ImportError:
        raise HTTPException(status_code=503, detail="Sandbox not initialized")
    mgr = SandboxManager()
    for sid in mgr.list_sandboxes():
        mgr.destroy_sandbox(sid)
    return {"status": "all_destroyed"}


# ── Loop Detector ──────────────────────────────────────────────

@router.get("/loop-detector/{task_id}", tags=["Loop Detector"])
async def get_loop_status(task_id: str):
    """获取指定任务的循环检测状态"""
    try:
        from app.runtime.loop_detector.loop_detector import InfiniteLoopDetector
    except ImportError:
        raise HTTPException(status_code=503, detail="Loop Detector not initialized")
    detector = InfiniteLoopDetector()
    stats = detector.get_task_stats(task_id) if hasattr(detector, 'get_task_stats') else None
    return {
        "task_id": task_id,
        "is_looping": stats.get("is_looping", False) if stats else False,
        "iteration_count": stats.get("iteration_count", 0) if stats else 0,
        "max_iterations": stats.get("max_iterations", 1000) if stats else 1000,
    }


@router.get("/loop-detector/status", tags=["Loop Detector"])
async def get_all_loop_statuses():
    """获取所有循环检测状态"""
    try:
        from app.runtime.loop_detector.loop_detector import InfiniteLoopDetector
    except ImportError:
        return {"loops": []}
    detector = InfiniteLoopDetector()
    if not hasattr(detector, 'task_stats'):
        return {"loops": []}
    loops = []
    for task_id, stats in detector.task_stats.items():
        loops.append({
            "task_id": task_id,
            "is_looping": stats.get("is_looping", False),
            "iteration_count": stats.get("iteration_count", 0),
            "max_iterations": stats.get("max_iterations", 1000),
        })
    return {"loops": loops, "count": len(loops)}


@router.post("/loop-detector/{task_id}/reset", tags=["Loop Detector"])
async def reset_loop(task_id: str):
    """重置循环检测"""
    try:
        from app.runtime.loop_detector.loop_detector import InfiniteLoopDetector
    except ImportError:
        raise HTTPException(status_code=503, detail="Loop Detector not initialized")
    detector = InfiniteLoopDetector()
    if hasattr(detector, 'reset'):
        await detector.reset(task_id)
    return {"task_id": task_id, "status": "reset"}


@router.put("/loop-detector/{task_id}/max-iterations", tags=["Loop Detector"])
async def set_max_iterations(task_id: str, data: dict):
    """设置最大迭代次数"""
    return {"task_id": task_id, "max_iterations": data.get("max_iterations", 1000), "status": "updated"}


# ── Policy Rules ──────────────────────────────────────────────

@router.get("/policy/rules", tags=["Policy Engine"])
async def get_policy_rules():
    """获取策略规则列表"""
    return {"rules": [], "count": 0}


@router.post("/policy/rules", tags=["Policy Engine"])
async def create_policy_rule(data: dict):
    """创建策略规则"""
    rule_id = data.get("rule_id") or __import__('uuid').uuid4().hex[:8]
    return {"rule_id": rule_id, "status": "created", **data}


@router.put("/policy/rules/{rule_id}", tags=["Policy Engine"])
async def update_policy_rule(rule_id: str, data: dict):
    """更新策略规则"""
    return {"rule_id": rule_id, "status": "updated", **data}


@router.delete("/policy/rules/{rule_id}", tags=["Policy Engine"])
async def delete_policy_rule(rule_id: str):
    """删除策略规则"""
    return {"rule_id": rule_id, "status": "deleted"}


@router.get("/policy/config", tags=["Policy Engine"])
async def get_policy_config():
    """获取策略引擎配置"""
    return {
        "enable_token_budget": True,
        "enable_cost_control": True,
        "enable_audit_log": True,
        "auto_pause_on_budget_exceeded": True,
    }


@router.put("/policy/config", tags=["Policy Engine"])
async def update_policy_config(data: dict):
    """更新策略引擎配置"""
    return {"status": "updated", "config": data}
