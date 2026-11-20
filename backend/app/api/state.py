"""
AI Runtime OS — State API
提供 State 读写 + Checkpoint 管理
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.runtime.state_manager.state_manager import StateManager
from app.runtime.state_manager.state_validator import StateValidator, StateTooLargeError
from app.runtime.checkpoint_manager.checkpoint_manager import CheckpointManager

logger = logging.getLogger("ai_runtime_os.api.state")
router = APIRouter()


def _get_state_mgr(db: AsyncSession = Depends(get_db)) -> StateManager:
    return StateManager(db)


def _get_checkpoint_mgr(db: AsyncSession = Depends(get_db)) -> CheckpointManager:
    return CheckpointManager(db)


# ══════════════════════════════════════════
# State API
# ══════════════════════════════════════════

@router.get("/{task_id}")
async def get_state(
    task_id: str,
    state_mgr: StateManager = Depends(_get_state_mgr),
):
    """获取任务的轻量 State"""
    state = await state_mgr.load(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="State not found for this task")
    return {
        "task_id": task_id,
        "state": state.to_dict(),
        "size_bytes": StateValidator.get_size(state.to_dict()),
    }


@router.post("/{task_id}/initialize")
async def initialize_state(
    task_id: str,
    goal: str = Query(""),
    project_id: str = Query(""),
    state_mgr: StateManager = Depends(_get_state_mgr),
):
    """为新任务初始化 State"""
    state = await state_mgr.initialize(task_id, goal, project_id)
    return {
        "task_id": task_id,
        "state": state.to_dict(),
        "initialized": True,
    }


@router.put("/{task_id}")
async def update_state(
    task_id: str,
    updates: dict,
    state_mgr: StateManager = Depends(_get_state_mgr),
):
    """
    部分更新 State 字段。
    Body: {"current_node": "planner", "workflow_status": "running"}
    """
    try:
        state = await state_mgr.update_field(task_id, updates)
    except StateTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    warnings = StateValidator.validate(state.to_dict())
    return {
        "task_id": task_id,
        "state": state.to_dict(),
        "size_bytes": StateValidator.get_size(state.to_dict()),
        "warnings": [
            {"field": w.field, "message": w.message, "current_size": w.current_size}
            for w in warnings
        ] if warnings else [],
    }


@router.get("/{task_id}/size")
async def get_state_size(
    task_id: str,
    state_mgr: StateManager = Depends(_get_state_mgr),
):
    """获取 State 字节大小"""
    try:
        size = await state_mgr.get_size(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task_id format (must be UUID)")
    limit = 100_000
    return {
        "task_id": task_id,
        "size_bytes": size,
        "limit_bytes": limit,
        "percent": round(size / limit * 100, 2) if limit else 0,
        "ok": size <= limit,
    }


# ══════════════════════════════════════════
# Checkpoint API
# ══════════════════════════════════════════

@router.post("/{task_id}/checkpoints")
async def save_checkpoint(
    task_id: str,
    event_seq_num: int | None = Query(None),
    cp_mgr: CheckpointManager = Depends(_get_checkpoint_mgr),
):
    """为任务保存当前 State 快照为 Checkpoint"""
    cp = await cp_mgr.save_checkpoint(task_id, event_seq_num)
    return {
        "id": str(cp.id),
        "task_id": str(cp.task_id),
        "created_at": cp.created_at.isoformat() if cp.created_at else None,
        "event_seq_num": cp.event_seq_num,
        "node": cp.state_snapshot.get("current_node", ""),
    }


@router.get("/{task_id}/checkpoints")
async def list_checkpoints(
    task_id: str,
    cp_mgr: CheckpointManager = Depends(_get_checkpoint_mgr),
):
    """列出任务所有 Checkpoint"""
    cps = await cp_mgr.list_checkpoints(task_id)
    return {"task_id": task_id, "checkpoints": cps, "count": len(cps)}


@router.get("/{task_id}/checkpoints/latest")
async def get_latest_checkpoint(
    task_id: str,
    cp_mgr: CheckpointManager = Depends(_get_checkpoint_mgr),
):
    """获取任务最新 Checkpoint"""
    cp = await cp_mgr.load_latest(task_id)
    if not cp:
        raise HTTPException(status_code=404, detail="No checkpoint found")
    return {
        "id": str(cp.id),
        "task_id": str(cp.task_id),
        "created_at": cp.created_at.isoformat() if cp.created_at else None,
        "event_seq_num": cp.event_seq_num,
        "state_snapshot": cp.state_snapshot,
    }


@router.get("/{task_id}/checkpoints/{checkpoint_id}")
async def get_checkpoint_detail(
    task_id: str,
    checkpoint_id: str,
    cp_mgr: CheckpointManager = Depends(_get_checkpoint_mgr),
):
    """获取指定 Checkpoint 的完整详情（含 state_snapshot）"""
    cp = await cp_mgr.load_checkpoint(checkpoint_id)
    if not cp or str(cp.task_id) != task_id:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return {
        "id": str(cp.id),
        "task_id": str(cp.task_id),
        "created_at": cp.created_at.isoformat() if cp.created_at else None,
        "event_seq_num": cp.event_seq_num,
        "state_snapshot": cp.state_snapshot,
    }


@router.post("/{task_id}/checkpoints/{checkpoint_id}/restore")
async def restore_from_checkpoint(
    task_id: str,
    checkpoint_id: str,
    cp_mgr: CheckpointManager = Depends(_get_checkpoint_mgr),
):
    """从指定 Checkpoint 恢复 State"""
    try:
        state = await cp_mgr.restore_from_checkpoint(task_id, checkpoint_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "task_id": task_id,
        "checkpoint_id": checkpoint_id,
        "state": state.to_dict(),
        "restored": True,
    }


@router.delete("/{task_id}/checkpoints/{checkpoint_id}")
async def delete_checkpoint(
    task_id: str,
    checkpoint_id: str,
    cp_mgr: CheckpointManager = Depends(_get_checkpoint_mgr),
):
    """删除指定 Checkpoint"""
    deleted = await cp_mgr.delete_checkpoint(checkpoint_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return {"deleted": True, "checkpoint_id": checkpoint_id}
