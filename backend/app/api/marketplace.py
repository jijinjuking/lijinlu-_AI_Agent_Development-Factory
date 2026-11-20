"""
W29-30: AI Marketplace — REST API

能力包市场 API 端点：
- 发布 / 下架 / 管理
- 搜索 / 浏览
- 安装 / 卸载 / 更新
- 评分 / 评价
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.runtime.marketplace.models import (
    InstallRecord,
    MarketplacePackage,
    MarketplaceStats,
    PackageRating,
    PackageStatus,
    PackageType,
    PackageVersion,
    SearchQuery,
    SearchResult,
)
from app.runtime.marketplace.package_manager import PackageManager
from app.runtime.marketplace.rating import RatingSystem
from app.runtime.marketplace.registry import MarketplaceRegistry
from app.runtime.marketplace.search_engine import SearchEngine

router = APIRouter(prefix="/marketplace", tags=["Marketplace"])

# ─── 全局单例 ────────────────────────────────────────────────────────────────

_registry = MarketplaceRegistry()
_package_manager = PackageManager()
_search_engine = SearchEngine()
_rating_system = RatingSystem()


# ─── 搜索与浏览 ─────────────────────────────────────────────────────────────

@router.get("/search", response_model=None)
async def search_packages(
    q: str = Query(default="", description="搜索关键词"),
    package_type: str | None = Query(default=None, alias="type"),
    category: str | None = Query(default=None),
    tags: str | None = Query(default=None),
    author: str | None = Query(default=None),
    sort_by: str = Query(default="relevance"),
    sort_order: str = Query(default="desc"),
    min_rating: float = Query(default=0.0, ge=0.0, le=5.0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """搜索能力包"""
    query = SearchQuery(
        keywords=q,
        package_type=PackageType(package_type) if package_type else None,
        category=category,
        tags=tags.split(",") if tags else [],
        author=author,
        sort_by=sort_by,
        sort_order=sort_order,
        min_rating=min_rating,
        page=page,
        page_size=page_size,
    )
    results = await _search_engine.search(query, _registry._packages)
    total = _registry.count_packages(
        package_type=query.package_type,
        category=query.category,
    )
    return {
        "items": [r.__dict__ for r in results],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/suggest")
async def suggest_packages(
    q: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
):
    """搜索建议"""
    suggestions = await _search_engine.suggest(q, limit)
    return {"items": suggestions}


@router.get("/packages")
async def list_packages(
    package_type: str | None = Query(default=None, alias="type"),
    category: str | None = Query(default=None),
    tags: str | None = Query(default=None),
    author: str | None = Query(default=None),
    sort_by: str = Query(default="updated"),
    sort_order: str = Query(default="desc"),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """浏览能力包列表"""
    pkg_type = PackageType(package_type) if package_type else None
    pkg_status = PackageStatus(status) if status else None
    tag_list = tags.split(",") if tags else None

    results = _registry.list_packages(
        package_type=pkg_type,
        category=category,
        tags=tag_list,
        author=author,
        sort_by=sort_by,
        sort_order=sort_order,
        status=pkg_status,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    total = _registry.count_packages(
        package_type=pkg_type,
        category=category,
    )
    return {
        "items": [p.__dict__ for p in results],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ─── 发布与版本管理 ─────────────────────────────────────────────────────────

@router.post("/packages")
async def publish_package(package: MarketplacePackage):
    """发布 / 更新能力包"""
    try:
        pkg = await _registry.publish(package)
        # 搜索索引同步
        await _search_engine.index(pkg)
        return {"package_id": pkg.package_id, "status": pkg.status.value}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/packages/{package_id}")
async def get_package(package_id: str):
    """获取能力包详情"""
    pkg = _registry.get_package(package_id)
    if pkg is None:
        raise HTTPException(status_code=404, detail="Package not found")
    return pkg.__dict__


@router.post("/packages/{package_id}/unpublish")
async def unpublish_package(package_id: str):
    """下架能力包"""
    try:
        pkg = await _registry.unpublish(package_id)
        await _search_engine.deindex(package_id)
        return {"package_id": pkg.package_id, "status": pkg.status.value}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/packages/{package_id}/deprecate")
async def deprecate_package(package_id: str):
    """弃用能力包"""
    try:
        pkg = await _registry.deprecate(package_id)
        return {"package_id": pkg.package_id, "status": pkg.status.value}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/packages/{package_id}")
async def delete_package(package_id: str):
    """物理删除能力包"""
    try:
        await _registry.delete_package(package_id)
        await _search_engine.deindex(package_id)
        return {"deleted": True}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/packages/{package_id}/versions")
async def get_package_versions(package_id: str):
    """获取能力包版本列表"""
    try:
        versions = await _registry.get_versions(package_id)
        return {"items": [v.__dict__ for v in versions]}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/packages/{package_id}/versions")
async def add_package_version(package_id: str, version: PackageVersion):
    """添加版本"""
    try:
        pkg = await _registry.add_version(package_id, version)
        return {"package_id": pkg.package_id, "version": version.version}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── 安装管理 ──────────────────────────────────────────────────────────────

@router.post("/packages/{package_id}/install")
async def install_package(
    package_id: str,
    version: str | None = Query(default=None),
    auto_update: bool = Query(default=False),
):
    """安装能力包"""
    pkg = _registry.get_package(package_id)
    if pkg is None:
        raise HTTPException(status_code=404, detail="Package not found")
    try:
        record = await _package_manager.install(
            pkg, version=version, auto_update=auto_update,
        )
        # 更新安装次数
        pkg.install_count += 1
        return record.__dict__
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/packages/{package_id}/uninstall")
async def uninstall_package(package_id: str):
    """卸载能力包"""
    try:
        record = await _package_manager.uninstall(package_id)
        return record.__dict__
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/installed")
async def list_installed(
    package_type: str | None = Query(default=None, alias="type"),
):
    """列出已安装的能力包"""
    pkg_type = PackageType(package_type) if package_type else None
    records = _package_manager.list_installed(package_type=pkg_type)
    return {"items": [r.__dict__ for r in records], "total": len(records)}


@router.get("/installed/check-updates")
async def check_installed_updates():
    """检查已安装包的更新"""
    updates = await _package_manager.check_updates(_registry._packages)
    return {"items": updates, "total": len(updates)}


@router.post("/installed/update-all")
async def update_all_installed():
    """批量更新所有已安装包"""
    records = await _package_manager.update_all(_registry._packages)
    return {"items": [r.__dict__ for r in records], "total": len(records)}


# ─── 评分与评价 ────────────────────────────────────────────────────────────

@router.post("/packages/{package_id}/ratings")
async def submit_rating(
    package_id: str,
    user_id: str = Query(...),
    score: float = Query(ge=1.0, le=5.0),
    title: str = Query(default=""),
    review: str = Query(default=""),
):
    """提交 / 更新评分"""
    pkg = _registry.get_package(package_id)
    if pkg is None:
        raise HTTPException(status_code=404, detail="Package not found")
    try:
        rating = await _rating_system.submit_rating(
            pkg, user_id=user_id, score=score, title=title, review=review,
        )
        return rating.__dict__
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/packages/{package_id}/ratings")
async def get_package_ratings(
    package_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
):
    """获取能力包评分列表"""
    if _registry.get_package(package_id) is None:
        raise HTTPException(status_code=404, detail="Package not found")
    ratings = _rating_system.get_package_ratings(
        package_id, limit=page_size, offset=(page - 1) * page_size,
    )
    return {
        "items": [r.__dict__ for r in ratings],
        "total": _rating_system.get_package_rating_count(package_id),
        "average": _rating_system.get_package_average_rating(package_id),
    }


@router.get("/packages/{package_id}/ratings/my")
async def get_my_rating(package_id: str, user_id: str = Query(...)):
    """获取当前用户对包的评分"""
    rating = _rating_system.get_user_rating(user_id, package_id)
    if rating is None:
        return {"rating": None}
    return {"rating": rating.__dict__}


@router.delete("/ratings/{rating_id}")
async def delete_rating(rating_id: str):
    """删除评分"""
    rating = _rating_system.get_rating(rating_id)
    if rating is None:
        raise HTTPException(status_code=404, detail="Rating not found")
    pkg = _registry.get_package(rating.package_id)
    await _rating_system.delete_rating(rating_id, pkg)
    return {"deleted": True}


# ─── 统计 ──────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_marketplace_stats():
    """市场统计"""
    stats = await _registry.get_stats()
    return stats.__dict__


@router.get("/stats/by-category")
async def stats_by_category():
    """按分类统计"""
    stats = await _registry.get_stats()
    return {"by_type": stats.by_type, "by_category": stats.by_category}


# ─── 管理 ──────────────────────────────────────────────────────────────────

@router.post("/admin/reindex")
async def reindex_search():
    """重建搜索索引（管理用）"""
    all_packages = list(_registry._packages.values())
    await _search_engine.reindex_all(all_packages)
    return {"indexed": _search_engine.get_index_count()}
