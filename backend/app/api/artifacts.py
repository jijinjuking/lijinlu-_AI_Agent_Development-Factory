"""
AI Runtime OS — Artifact API

基础 CRUD：
  GET    /artifacts               — 列表（支持 task_id 过滤）
  GET    /artifacts/{id}          — 元数据详情
  GET    /artifacts/{id}/content  — 原始内容
  POST   /artifacts               — 创建
  DELETE /artifacts/{id}          — 删除

版本管理（W23-24）：
  GET    /artifacts/{id}/versions         — 版本链（完整历史）
  POST   /artifacts/{id}/versions         — 创建新版本
  GET    /artifacts/{id}/diff             — 与另一版本 diff
  POST   /artifacts/{id}/rollback         — 回滚到指定版本（创建新版本）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.runtime.artifact_store import ArtifactStore

router = APIRouter()


# ══════════════════════════════════════════════════════════════
# 基础 CRUD
# ══════════════════════════════════════════════════════════════

@router.get("")
async def list_artifacts(
    task_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """列出所有 Artifact（支持按 task_id 过滤）"""
    store = ArtifactStore(db)
    if task_id:
        items = await store.list_by_task(task_id)
    else:
        items = await store.list_all(limit=limit, offset=offset)
    count = await store.count()
    return {"artifacts": items, "count": count}


@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str, db: AsyncSession = Depends(get_db)):
    """获取 Artifact 元数据"""
    store = ArtifactStore(db)
    meta = await store.get_meta(artifact_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return meta


@router.get("/{artifact_id}/content")
async def get_artifact_content(artifact_id: str, db: AsyncSession = Depends(get_db)):
    """获取 Artifact 原始文本内容"""
    store = ArtifactStore(db)
    try:
        content = await store.load(artifact_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Artifact not found")
    meta = await store.get_meta(artifact_id)
    media_type = "text/plain; charset=utf-8"
    if meta and meta["artifact_type"].endswith("_doc"):
        media_type = "text/markdown; charset=utf-8"
    return PlainTextResponse(content, media_type=media_type)


@router.post("")
async def create_artifact(body: dict, db: AsyncSession = Depends(get_db)):
    """创建新 Artifact"""
    task_id = body.get("task_id")
    artifact_type = body.get("artifact_type")
    content = body.get("content", "")
    metadata = body.get("metadata")

    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")
    if not artifact_type:
        raise HTTPException(status_code=400, detail="artifact_type is required")

    store = ArtifactStore(db)
    try:
        aid = await store.save(
            task_id=task_id,
            artifact_type=artifact_type,
            content=content,
            metadata=metadata,
            parent_artifact_id=body.get("parent_artifact_id"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    meta = await store.get_meta(aid)
    return {"artifact_id": aid, "artifact": meta}


@router.delete("/{artifact_id}")
async def delete_artifact(artifact_id: str, db: AsyncSession = Depends(get_db)):
    """删除 Artifact（文件 + 元数据）"""
    store = ArtifactStore(db)
    ok = await store.delete(artifact_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"deleted": artifact_id}


# ══════════════════════════════════════════════════════════════
# 版本管理 API（W23-24）
# ══════════════════════════════════════════════════════════════

@router.get("/{artifact_id}/versions")
async def get_artifact_versions(artifact_id: str, db: AsyncSession = Depends(get_db)):
    """
    获取指定 Artifact 的完整版本链（从最旧到最新）。
    通过 parent_artifact_id 向上追溯，返回所有祖先版本。
    """
    store = ArtifactStore(db)
    meta = await store.get_meta(artifact_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    chain = await store.get_version_chain(artifact_id)
    return {
        "artifact_id": artifact_id,
        "versions": chain,
        "count": len(chain),
        "current_version": meta["version"],
    }


@router.post("/{artifact_id}/versions")
async def create_artifact_version(
    artifact_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    基于已有 Artifact 创建新版本（继承 task_id 和 artifact_type）。
    Body: {"content": "...", "metadata": {...}}
    """
    content = body.get("content")
    if content is None:
        raise HTTPException(status_code=400, detail="content is required")

    store = ArtifactStore(db)
    try:
        new_id = await store.create_new_version(
            parent_artifact_id=artifact_id,
            content=content,
            metadata=body.get("metadata"),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    new_meta = await store.get_meta(new_id)
    return {"artifact_id": new_id, "artifact": new_meta}


@router.get("/{artifact_id}/diff")
async def diff_artifacts(
    artifact_id: str,
    compare_with: str = Query(..., description="对比的 artifact_id（通常是另一个版本）"),
    db: AsyncSession = Depends(get_db),
):
    """生成两个 Artifact 版本之间的 unified diff"""
    store = ArtifactStore(db)
    try:
        diff_text = await store.diff(compare_with, artifact_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"diff": diff_text, "base_id": compare_with, "target_id": artifact_id}


@router.post("/{artifact_id}/rollback")
async def rollback_artifact(
    artifact_id: str,
    body: dict | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    回滚到指定版本：读取目标版本内容，创建为最新版本。

    默认以 artifact_id 作为回滚目标（即「恢复到 artifact_id 对应的内容」）。
    可在 body 中传 {"target_version_id": "..."} 覆盖目标。
    """
    store = ArtifactStore(db)
    target_id = (body or {}).get("target_version_id", artifact_id)

    try:
        new_id = await store.rollback_to(target_artifact_id=target_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    new_meta = await store.get_meta(new_id)
    return {
        "artifact_id": new_id,
        "rolled_back_from": target_id,
        "artifact": new_meta,
        "message": f"成功回滚到版本 v{(new_meta or {}).get('version', '?')-1}，已创建新版本",
    }
