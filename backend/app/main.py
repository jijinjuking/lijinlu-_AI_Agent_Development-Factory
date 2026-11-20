"""
AI Runtime OS — FastAPI 应用入口
集成所有 Runtime 组件（Kernel / EventBus / SSE / Scheduler / ModelRouter / PolicyEngine / Sandbox / LoopDetector）
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db, async_session_factory

logger = logging.getLogger("ai_runtime_os")

# ---------------------------------------------------------------------------
# Runtime Kernel — 模块级变量（通过 app.state 暴露给 API）
# ---------------------------------------------------------------------------
_kernel = None


def get_kernel():
    """获取全局 RuntimeKernel 实例（供 API 层使用）"""
    return _kernel


async def _load_runtime_config(db) -> dict:
    """从 runtime_settings 表加载配置，返回 dict"""
    from app.models.settings import RuntimeSetting
    from sqlalchemy import select
    default_settings = {
        "max_concurrency": 8,
        "default_timeout_minutes": 30,
        "auto_retry_count": 2,
        "log_retention_days": 30,
        "notify_on_complete": True,
        "notify_on_failure": True,
        "cost_alert_threshold": 20.0,
        "notification_channels": ["webhook"],
    }
    try:
        result = await db.execute(select(RuntimeSetting))
        rows = {r.key: r for r in result.scalars().all()}
        cfg = {}
        for key, default in default_settings.items():
            row = rows.get(key)
            if row:
                raw = row.value
                if isinstance(default, bool):
                    cfg[key] = raw.lower() == "true"
                elif isinstance(default, int):
                    cfg[key] = int(raw) if raw else default
                elif isinstance(default, float):
                    cfg[key] = float(raw) if raw else default
                else:
                    cfg[key] = raw
            else:
                cfg[key] = default
        return cfg
    except Exception:
        return default_settings


async def _init_runtime_kernel():
    """初始化所有 Runtime 组件并启动 Kernel"""
    global _kernel

    # --- Lazy imports（避免模块级循环依赖）---
    from app.runtime.state_manager import StateManager
    from app.runtime.checkpoint_manager import CheckpointManager
    from app.runtime.policy_engine import PolicyEngine
    from app.runtime.model_router import default_router
    from app.runtime.scheduler import default_scheduler, Scheduler
    from app.runtime.loop_detector import InfiniteLoopDetector
    from app.runtime.sandbox import SandboxManager
    from app.runtime.kernel import RuntimeKernel
    from app.core.event_bus import event_bus
    from app.core.sse_manager import sse_manager
    from app.services.llm_service import llm_service

    # --- 创建数据库会话（Kernel 生命周期内持有）---
    db = async_session_factory()

    # --- 加载运行时配置 ---
    runtime_config = await _load_runtime_config(db)

    # --- 基础组件 ---
    state_mgr = StateManager(db)
    checkpoint_mgr = CheckpointManager(db, state_mgr)
    policy_engine = PolicyEngine()
    loop_detector = InfiniteLoopDetector()
    sandbox_mgr = SandboxManager()

    # --- Scheduler（复用全局单例）---
    scheduler: Scheduler = default_scheduler

    # --- Kernel ---
    kernel = RuntimeKernel(
        state_manager=state_mgr,
        scheduler=scheduler,
        checkpoint_manager=checkpoint_mgr,
        policy_engine=policy_engine,
        model_router=default_router,
        loop_detector=loop_detector,
        sandbox_manager=sandbox_mgr,
        event_bus=event_bus,
        llm_service=llm_service,
        runtime_config=runtime_config,
    )

    # --- 注入 Recovery Manager ---
    try:
        from app.runtime.recovery_manager import (
            FailureDetector, StateRollback, RecoveryOrchestrator,
        )
        detector = FailureDetector()
        rollback = StateRollback(checkpoint_mgr, state_mgr)
        recovery_mgr = RecoveryOrchestrator(detector, rollback)
        await kernel.inject_recovery_manager(recovery_mgr)
        logger.info("RecoveryOrchestrator 注入完成")
    except (ImportError, TypeError) as e:
        logger.warning(f"RecoveryOrchestrator 注入跳过: {e}")

    # --- 启动 Kernel ---
    await kernel.start()
    _kernel = kernel
    logger.info("RuntimeKernel 初始化完成")

    return kernel, db


async def _shutdown_runtime_kernel(kernel, db):
    """关闭 Runtime Kernel 并清理资源"""
    global _kernel
    await kernel.stop()
    try:
        await db.close()
    except Exception:
        pass
    _kernel = None
    logger.info("RuntimeKernel 已停止")


def _setup_event_bus_sse_bridge():
    """将 EventBus 的所有事件桥接到 SSE Manager"""
    from app.core.event_bus import event_bus
    from app.core.sse_manager import sse_manager

    async def _bridge(subscriber_data: dict):
        try:
            event_type = subscriber_data.get("type", "unknown")
            task_id = subscriber_data.get("task_id", "")
            payload = subscriber_data.get("payload", {})
            await sse_manager.publish(str(event_type), payload or {}, task_id if task_id else None)
        except Exception:
            pass  # SSE 推送失败不影响 EventBus

    event_bus.subscribe_all(_bridge)
    logger.info("EventBus → SSE 桥接已建立")


def _setup_event_bus_websocket_bridge():
    """将 EventBus 的所有事件桥接到 WebSocket Manager"""
    from app.core.event_bus import event_bus
    from app.core.websocket_manager import manager

    async def _bridge(subscriber_data: dict):
        try:
            event_type = subscriber_data.get("type", "unknown")
            task_id = subscriber_data.get("task_id", "")
            payload = subscriber_data.get("payload", {})
            # 推送到 WebSocket（按 task_id 和全局）
            await manager.send_to_task(str(task_id), str(event_type), payload or {})
            # 也广播到所有连接（如果需要）
            # await manager.broadcast(str(event_type), payload or {})
        except Exception:
            pass  # WebSocket 推送失败不影响 EventBus

    event_bus.subscribe_all(_bridge)
    logger.info("EventBus → WebSocket 桥接已建立")


# ============================================================================
# FastAPI 应用
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期：初始化 DB → 启动 Kernel → 桥接 EventBus/SSE"""
    if settings.debug:
        await init_db()
        logger.info("数据库表初始化完成")

    # 初始化 Runtime Kernel
    kernel = None
    db = None
    try:
        kernel, db = await _init_runtime_kernel()
        app.state.kernel = kernel
        app.state.kernel_db = db

        # EventBus → SSE 桥接
        _setup_event_bus_sse_bridge()

        # EventBus → WebSocket 桥接
        _setup_event_bus_websocket_bridge()
    except Exception:
        logger.exception("RuntimeKernel 初始化失败，后端将以降级模式运行")

    yield

    # 清理
    if kernel and db:
        await _shutdown_runtime_kernel(kernel, db)


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# ── 全局异常处理器（开发模式：把所有异常返回 JSON detail）───
if settings.debug:
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    @app.exception_handler(Exception)
    async def _global_exc_handler(request: Request, exc: Exception):
        import traceback
        tb = traceback.format_exc()
        print(f"GLOBAL EXCEPTION: {type(exc).__name__}: {exc}\n{tb}", flush=True)
        return JSONResponse(
            status_code=500,
            content={"detail": f"{type(exc).__name__}: {str(exc)[:500]}"},
        )


# CORS — 允许前端 dev server 和 Tauri
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
from app.api.router import api_router  # noqa: E402
app.include_router(api_router, prefix=settings.api_prefix)

# 注册 Auth 路由（直接注册，绕过 router.py 排查）
from app.api.auth import router as auth_router  # noqa: E402
app.include_router(auth_router, prefix=f"{settings.api_prefix}/auth")

# 注册 WebSocket 路由
from app.api.ws import router as ws_router  # noqa: E402
app.include_router(ws_router, prefix=f"{settings.api_prefix}")


# ── 临时 WebSocket 测试端点（绕过路由，直接挂载）───
@app.websocket("/api/v1/ws-test")
async def websocket_test_endpoint(websocket: WebSocket):
    """临时测试端点，无认证，验证 WebSocket 基础功能"""
    print(f"[DEBUG] WebSocket test endpoint HIT! client={websocket.client}", flush=True)
    logger.info(f"WebSocket test endpoint HIT! client={websocket.client}")
    await websocket.accept()
    print(f"[DEBUG] WebSocket accepted!", flush=True)
    logger.info("WebSocket test endpoint connected")
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except Exception:
        logger.info("WebSocket test endpoint disconnected")


@app.get("/health")
async def health_check():
    from app.core.event_bus import event_bus
    kernel = _kernel

    kernel_status = None
    if kernel:
        ks = kernel.get_status()
        kernel_status = {
            "active_tasks": ks.active_tasks,
            "completed_tasks": ks.completed_tasks,
            "failed_tasks": ks.failed_tasks,
            "paused_tasks": ks.paused_tasks,
            "total_tasks": ks.total_tasks,
            "uptime_seconds": round(ks.uptime_seconds, 1),
            "version": ks.version,
        }
        component_statuses = kernel.get_component_statuses()
    else:
        kernel_status = None
        component_statuses = {"event_bus": "not_configured", "sse_manager": "not_configured"}

    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "database": "sqlite" if settings.is_sqlite else "postgresql",
        "kernel": kernel_status,
        "runtime_components": component_statuses,
    }
