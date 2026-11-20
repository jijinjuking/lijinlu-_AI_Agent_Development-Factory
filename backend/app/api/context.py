"""
Context API — 上下文引擎 REST 端点
提供语义搜索、上下文构建、索引管理、缓存管理
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.runtime.context_engine import context_engine
from app.runtime.context_engine.retrieval import VectorDoc
from app.models.context import ContextIndex

logger = logging.getLogger(__name__)

router = APIRouter(tags=["context"])


# ---- Request/Response Schemas ----

class IndexRequest(BaseModel):
    text: str = Field(..., description="要索引的文本内容")
    metadata: dict = Field(default_factory=dict, description="元信息")
    source_type: str = Field(default="manual", description="manual | memory | document")
    source_id: str = Field(default="", description="来源 ID")

class IndexBatchRequest(BaseModel):
    documents: list[dict] = Field(..., description="批量文档 [{content: ..., ...}, ...]")
    content_key: str = Field(default="content", description="内容字段名")

class SearchRequest(BaseModel):
    query: str = Field(..., description="搜索查询")
    top_k: int = Field(default=5, ge=1, le=50)
    filters: dict | None = None

class BuildRequest(BaseModel):
    query: str = Field(..., description="上下文查询")
    project_id: str = Field(default="", description="项目 ID")
    token_budget: int = Field(default=2000, ge=100, le=16000, description="Token 预算")
    use_cache: bool = Field(default=True)

class InjectRequest(BaseModel):
    query: str = Field(..., description="上下文查询")
    project_id: str = Field(default="")
    token_budget: int = Field(default=2000, ge=100, le=16000)


# ---- Endpoints ----

@router.get("/stats")
async def get_engine_stats():
    """获取 Context Engine 统计信息"""
    return {
        "status": "ok",
        **context_engine.stats,
    }


@router.post("/index")
async def index_text(req: IndexRequest, db: AsyncSession = Depends(get_db)):
    """索引单条文本"""
    try:
        ids = await context_engine.index(req.text, req.metadata)

        # 写入 ContextIndex 记录
        content_hash = hashlib.sha256(req.text.encode()).hexdigest()
        index_entry = ContextIndex(
            source_type=req.source_type,
            source_id=req.source_id or None,
            title=req.metadata.get("title", ""),
            content_hash=content_hash,
            chunk_count=len(ids),
            vector_ids=",".join(ids) if ids else "",
            token_count=sum(len(t) for t in req.text.split()),
        )
        db.add(index_entry)
        await db.flush()

        return {
            "status": "ok",
            "indexed_chunks": len(ids),
            "vector_ids": ids,
            "content_hash": content_hash,
        }
    except Exception as e:
        logger.error("Index failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Index failed: {str(e)}")


@router.post("/index/batch")
async def index_batch(req: IndexBatchRequest, db: AsyncSession = Depends(get_db)):
    """批量索引文档"""
    try:
        ids = await context_engine.index_batch(req.documents, req.content_key)
        return {
            "status": "ok",
            "indexed_docs": len(req.documents),
            "total_chunks": len(ids),
            "vector_ids": ids,
        }
    except Exception as e:
        logger.error("Batch index failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Batch index failed: {str(e)}")


@router.post("/search")
async def semantic_search(req: SearchRequest):
    """语义搜索"""
    try:
        results = await context_engine.search(
            req.query, top_k=req.top_k, filters=req.filters,
        )
        return {
            "status": "ok",
            "query": req.query,
            "results": results,
            "count": len(results),
        }
    except Exception as e:
        logger.error("Search failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/build")
async def build_context(req: BuildRequest):
    """构建上下文（搜索 + 拼接）"""
    try:
        result = await context_engine.build(
            query=req.query,
            project_id=req.project_id,
            token_budget=req.token_budget,
            use_cache=req.use_cache,
        )
        return {
            "status": "ok",
            "context": result.context,
            "sources": result.sources,
            "token_count": result.token_count,
            "cache_hit": result.cache_hit,
            "retrieval_count": result.retrieval_count,
        }
    except Exception as e:
        logger.error("Build failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Build failed: {str(e)}")


@router.post("/inject")
async def inject_context(req: InjectRequest):
    """注入上下文（返回格式化的 prompt 块）"""
    try:
        injected = await context_engine.inject(
            query=req.query,
            project_id=req.project_id,
            token_budget=req.token_budget,
        )
        return {
            "status": "ok",
            "injected_context": injected,
            "has_context": bool(injected),
        }
    except Exception as e:
        logger.error("Inject failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Inject failed: {str(e)}")


@router.get("/cache/stats")
async def cache_stats():
    """缓存统计"""
    return {"status": "ok", **context_engine.cache.stats}


@router.post("/cache/clear")
async def clear_cache(project_id: str = ""):
    """清空缓存"""
    await context_engine.clear_cache(project_id)
    return {"status": "ok", "message": "Cache cleared"}


@router.post("/index/clear")
async def clear_index():
    """清空向量索引"""
    await context_engine.clear_index()
    return {"status": "ok", "message": "Index cleared"}


@router.get("/index/list")
async def list_index_entries(
    source_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """列出索引条目"""
    stmt = select(ContextIndex).order_by(ContextIndex.created_at.desc())

    if source_type:
        stmt = stmt.where(ContextIndex.source_type == source_type)
    if limit:
        stmt = stmt.limit(limit)
    if offset:
        stmt = stmt.offset(offset)

    result = await db.execute(stmt)
    entries = result.scalars().all()

    count_stmt = select(func.count(ContextIndex.id))
    if source_type:
        count_stmt = count_stmt.where(ContextIndex.source_type == source_type)
    total = (await db.execute(count_stmt)).scalar() or 0

    return {
        "status": "ok",
        "entries": [
            {
                "id": str(e.id),
                "source_type": e.source_type,
                "source_id": e.source_id,
                "title": e.title,
                "chunk_count": e.chunk_count,
                "token_count": e.token_count,
                "status": e.status,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
        "total": total,
    }


@router.delete("/index/{entry_id}")
async def delete_index_entry(entry_id: str, db: AsyncSession = Depends(get_db)):
    """删除索引条目"""
    from uuid import UUID
    try:
        uid = UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    result = await db.execute(select(ContextIndex).where(ContextIndex.id == uid))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Index entry not found")

    # 标记为删除
    entry.status = "deleted"
    await db.flush()

    return {"status": "ok", "message": f"Entry {entry_id} marked as deleted"}
