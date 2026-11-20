"""
ORM 对象 → API 响应 dict 转换工具
处理 UUID→str、datetime→ISO str、逗号分隔→list 等映射
"""
from __future__ import annotations

from datetime import datetime


def _to_str(v) -> str:
    """通用 → str"""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _split_tags(tags: str) -> list[str]:
    """逗号分隔标签 → list[str]"""
    if not tags:
        return []
    return [t.strip() for t in tags.split(",") if t.strip()]


def agent_to_dict(a) -> dict:
    """Agent ORM → API dict"""
    return {
        "id": _to_str(a.id),
        "name": a.name,
        "role": a.role,
        "status": a.status,
        "model": a.model,
        "model_mode": a.model_mode,
        "description": a.description or "",
        "system_prompt": a.system_prompt or None,
        "capability_tags": a.capability_tags or "",
        "max_retries": a.max_retries,
        "timeout_sec": a.timeout_sec,
        "is_active": a.is_active,
        "total_tasks": a.total_tasks,
        "completed_tasks": a.completed_tasks,
        "failed_tasks": a.failed_tasks,
        "avg_duration": a.avg_duration,
        "total_tokens": a.total_tokens,
        "total_cost": a.total_cost,
        "created_at": _to_str(a.created_at),
        "last_active_at": _to_str(a.updated_at),
    }


def tpl_to_dict(t) -> dict:
    """PipelineTemplate ORM → API dict"""
    return {
        "id": _to_str(t.id),
        "name": t.name,
        "description": t.description or "",
        "icon": t.icon,
        "category": t.category,
        "tags": _split_tags(t.tags),
        "steps": t.steps_json or [],
        "avg_duration": t.avg_duration,
        "success_rate": t.success_rate,
        "created_at": _to_str(t.created_at),
        "updated_at": _to_str(t.updated_at),
    }


def run_to_dict(r) -> dict:
    """PipelineRun ORM → API dict（字段名对齐前端 PipelineRun 类型）"""
    total = r.total_steps or 0
    completed = r.completed_steps or 0
    progress = round((completed / total * 100), 1) if total > 0 else 0
    return {
        "id": _to_str(r.id),
        "template_id": _to_str(r.template_id) if r.template_id else "",
        "template_name": r.template_name,
        "status": r.status,
        "current_step_id": r.current_step or "",
        "current_step_name": r.current_step or "",
        "progress": progress,
        "result": "",
        "error": "",
        "created_at": _to_str(r.created_at),
        "started_at": _to_str(r.started_at),
        "completed_at": _to_str(r.completed_at),
        "updated_at": _to_str(r.completed_at or r.started_at),
        "duration": r.duration or None,
        "total_steps": r.total_steps,
        "completed_steps": r.completed_steps,
        "failed_steps": r.failed_steps,
        "triggered_by": r.triggered_by,
        "cost": r.cost,
    }


def skill_to_dict(s) -> dict:
    """Skill ORM → API dict"""
    return {
        "id": _to_str(s.id),
        "name": s.name,
        "description": s.description or "",
        "category": s.category,
        "icon": s.icon,
        "author": s.author,
        "version": s.version,
        "downloads": s.downloads,
        "rating": s.rating,
        "installed": s.installed,
        "size": s.size,
        "tags": _split_tags(s.tags),
        "updated_at": _to_str(s.updated_at),
        "requires_config": s.requires_config,
        "config_fields": _split_tags(s.config_fields),
    }


def memory_to_dict(m) -> dict:
    """MemoryEntry ORM → API dict"""
    return {
        "id": _to_str(m.id),
        "layer": m.layer,
        "title": m.title,
        "content": m.content or "",
        "tags": _split_tags(m.tags),
        "created_at": _to_str(m.created_at),
        "updated_at": _to_str(m.updated_at),
        "source": m.source,
        "importance": m.importance,
        "token_estimate": m.token_estimate,
    }


def llmcall_to_dict(c) -> dict:
    """LLMCall ORM → CostRecord dict"""
    return {
        "id": _to_str(c.id),
        "date": _to_str(c.created_at),
        "agent_id": _to_str(c.agent_id) if c.agent_id else "",
        "agent_name": c.agent_name,
        "model": c.model,
        "task_type": c.task_type,
        "prompt_tokens": c.prompt_tokens,
        "completion_tokens": c.completion_tokens,
        "total_tokens": c.total_tokens,
        "cost": round(c.estimated_cost, 2),
        "duration": c.latency_ms,
    }


def model_to_dict(m) -> dict:
    """ModelConfig ORM → API dict"""
    return {
        "id": _to_str(m.id),
        "name": m.name,
        "model_id": getattr(m, 'model_id', '') or '',
        "provider": m.provider,
        "endpoint": m.endpoint or "",
        "api_base": getattr(m, 'api_base', '') or m.endpoint or "",
        "api_key_id": getattr(m, 'api_key_id', None) or None,
        "api_key_label": "",  # 由 API 层 JOIN 填充
        "enabled": m.enabled,
        "default_for": _split_tags(m.default_for),
        "max_tokens": m.max_tokens,
        "temperature": m.temperature,
        "cost_input_per_1k": getattr(m, 'cost_input_per_1k', 0.0) or 0.0,
        "cost_output_per_1k": getattr(m, 'cost_output_per_1k', 0.0) or 0.0,
        "api_key_configured": m.api_key_configured,
    }


def apikey_to_dict(k) -> dict:
    """ApiKey ORM → API dict"""
    return {
        "id": _to_str(k.id),
        "provider": k.provider,
        "label": k.label,
        "masked_key": k.masked_key,
        "created_at": _to_str(k.created_at),
        "last_used": k.last_used or None,
        "enabled": k.enabled,
    }


def perm_to_dict(p) -> dict:
    """AgentPermission ORM → API dict"""
    return {
        "id": _to_str(p.id),
        "role_id": p.role_id,
        "role_name": p.role_name,
        "can_create_pipeline": p.can_create_pipeline,
        "can_deploy": p.can_deploy,
        "can_access_network": p.can_access_network,
        "can_write_files": p.can_write_files,
        "can_execute_commands": p.can_execute_commands,
        "max_concurrency": p.max_concurrency,
        "max_tokens_per_task": p.max_tokens_per_task,
        "max_daily_cost": p.max_daily_cost,
    }


# ── Kanban 列规范化映射（backlog/ready/pending → todo，running → in_progress） ──
COLUMN_MAP: dict[str, str] = {
    "backlog": "todo", "ready": "todo", "pending": "todo",
    "running": "in_progress", "failed": "failed",
}


def task_to_dict(t) -> dict:
    """Task ORM → dict（对齐前端 KanbanTask 类型）"""
    raw_col = t.kanban_column or "todo"
    kanban_col = COLUMN_MAP.get(raw_col, raw_col)

    return {
        "id": _to_str(t.id),
        "title": t.title or t.name,
        "goal_description": t.goal_description,
        "agentId": _to_str(t.agent_id) if t.agent_id else None,
        "agentName": t.agent_name or "",
        "status": kanban_col,        # 前端用 kanban_column 作为 status
        "kanban_column": kanban_col,
        "priority": t.priority,
        "createdAt": _to_str(t.created_at),
        "updatedAt": _to_str(t.updated_at),
        "startedAt": _to_str(t.started_at) if t.started_at else None,
        "completedAt": _to_str(t.completed_at) if t.completed_at else None,
        "duration": t.duration,
        "tokenUsage": t.token_usage,
        "cost": t.cost,
        "tags": _split_tags(t.tags),
        "workflow_graph": t.workflow_graph_json or None,
    }
