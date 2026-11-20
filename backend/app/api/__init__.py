# AI Runtime OS — API Routes
from fastapi import APIRouter
from app.api import agents, pipelines, settings, dashboard, costs, memory, skills, traces, tasks, runtime_ops

router = APIRouter(prefix="/api/v1")
router.include_router(agents.router, prefix="/agents")
router.include_router(pipelines.router, prefix="/pipelines")
router.include_router(settings.router, prefix="/settings")
router.include_router(dashboard.router, prefix="/dashboard")
router.include_router(costs.router, prefix="/costs")
router.include_router(memory.router, prefix="/memory")
router.include_router(skills.router, prefix="/skills")
router.include_router(traces.router, prefix="/traces")
router.include_router(tasks.router, prefix="/tasks")
router.include_router(runtime_ops.router, prefix="/runtime")

