"""
API Router — 总路由注册
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.dashboard import router as dashboard_router
from app.api.agents import router as agents_router
from app.api.traces import router as traces_router
from app.api.pipelines import router as pipelines_router
from app.api.skills import router as skills_router
from app.api.memory import router as memory_router
from app.api.costs import router as costs_router
from app.api.settings import router as settings_router
from app.api.tasks import router as tasks_router
from app.api.events import router as events_router
from app.api.state import router as state_router
from app.api.artifacts import router as artifacts_router
from app.api.tools import router as tools_router
from app.api.context import router as context_router
from app.api.runtime_ops import router as runtime_ops_router
from app.api.evaluation import router as evaluation_router
from app.api.k8s import router as k8s_router
from app.api.multi_node import router as multi_node_router
from app.api.marketplace import router as marketplace_router
from app.api.federation import router as federation_router
from app.api.tenant import router as tenant_router
from app.api.performance import router as performance_router
from app.api.projects import router as projects_router
from app.api.issues import router as issues_router
from app.api.auth import router as auth_router

api_router = APIRouter()

api_router.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(agents_router, prefix="/agents", tags=["Agents"])
api_router.include_router(traces_router, prefix="/traces", tags=["Traces"])
api_router.include_router(pipelines_router, prefix="/pipelines", tags=["Pipelines"])
api_router.include_router(skills_router, prefix="/skills", tags=["Skills"])
api_router.include_router(memory_router, prefix="/memory", tags=["Memory"])
api_router.include_router(costs_router, prefix="/costs", tags=["Costs"])
api_router.include_router(settings_router, prefix="/settings", tags=["Settings"])
api_router.include_router(tasks_router, prefix="/tasks", tags=["Tasks"])
api_router.include_router(events_router, tags=["Events"])
api_router.include_router(state_router, prefix="/state", tags=["State & Checkpoints"])
api_router.include_router(artifacts_router, prefix="/artifacts", tags=["Artifacts"])
api_router.include_router(tools_router, prefix="/tools", tags=["Tools"])
api_router.include_router(context_router, prefix="/context", tags=["Context"])
api_router.include_router(runtime_ops_router, prefix="/runtime", tags=["RuntimeOps"])
api_router.include_router(evaluation_router, prefix="/evaluation", tags=["Evaluation"])
api_router.include_router(k8s_router, prefix="/k8s", tags=["K8s Scheduler"])
api_router.include_router(multi_node_router, prefix="/multi-node", tags=["Multi-Node"])
api_router.include_router(marketplace_router, tags=["Marketplace"])
api_router.include_router(federation_router, tags=["Federation"])
api_router.include_router(tenant_router, tags=["Tenants"])
api_router.include_router(performance_router, tags=["Performance"])
api_router.include_router(projects_router, prefix="/projects", tags=["Projects"])
api_router.include_router(issues_router, prefix="/issues", tags=["Issues"])
api_router.include_router(auth_router, prefix="/auth", tags=["Auth"])
