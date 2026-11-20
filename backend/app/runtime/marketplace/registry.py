"""
W29-30: AI Marketplace — 市场注册中心

管理能力包的上架/下架/版本/订阅。所有操作基于内存索引 + 可扩展持久化。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from app.runtime.marketplace.models import (
    MarketplacePackage,
    MarketplaceStats,
    PackageStatus,
    PackageType,
    PackageVersion,
)


class MarketplaceRegistry:
    """能力包注册中心

    核心职责：
    - 上架 / 下架 / 归档
    - 版本发布与获取
    - 搜索索引同步通知
    - 统计聚合
    """

    def __init__(self):
        self._packages: dict[str, MarketplacePackage] = {}
        self._by_name: dict[str, str] = {}              # name -> package_id
        self._by_type: dict[PackageType, set[str]] = {
            t: set() for t in PackageType
        }
        self._by_category: dict[str, set[str]] = {}     # category -> {package_id}
        self._by_tag: dict[str, set[str]] = {}          # tag -> {package_id}
        self._on_publish_hooks: list = []               # 发布/更新回调
        self._on_unpublish_hooks: list = []

    # ── 发布与下架 ──────────────────────────────────────────────────────────

    async def publish(self, package: MarketplacePackage) -> MarketplacePackage:
        """发布或更新能力包

        若同名包已存在则更新（保留统计字段），否则新增。
        """
        if package.name in self._by_name:
            existing_id = self._by_name[package.name]
            if existing_id != package.package_id:
                raise ValueError(
                    f"Package name '{package.name}' already registered as {existing_id}"
                )
            # 更新已有包，保留下载/安装统计
            existing = self._packages[package.package_id]
            existing.display_name = package.display_name
            existing.package_type = package.package_type
            existing.status = package.status
            existing.description = package.description
            existing.long_description = package.long_description
            existing.tags = package.tags
            existing.category = package.category
            existing.icon_url = package.icon_url
            existing.homepage_url = package.homepage_url
            existing.entry_point = package.entry_point
            existing.manifest = package.manifest
            existing.config_schema = package.config_schema
            existing.env_template = package.env_template
            existing.license_type = package.license_type
            existing.updated_at = datetime.now()

            # 新版本添加
            if package.version != existing.version:
                await self._add_version(existing, package.version)
                existing.version = package.version

            pkg = existing
            action = "updated"
        else:
            # 首次发布
            self._packages[package.package_id] = package
            self._by_name[package.name] = package.package_id
            self._by_type[package.package_type].add(package.package_id)
            self._index_categories(package)
            self._index_tags(package)

            # 自动添加初始版本
            if not package.versions:
                await self._add_version(package, package.version)

            pkg = package
            action = "published"

        if package.status == PackageStatus.PUBLISHED and not pkg.published_at:
            pkg.published_at = datetime.now()

        # 触发发布钩子（通知搜索引擎等）
        await self._fire_publish_hooks(pkg, action)
        return pkg

    async def unpublish(self, package_id: str) -> MarketplacePackage:
        """下架（归档）能力包"""
        pkg = self._get_or_raise(package_id)
        pkg.status = PackageStatus.ARCHIVED
        pkg.updated_at = datetime.now()
        await self._fire_unpublish_hooks(pkg)
        return pkg

    async def deprecate(self, package_id: str) -> MarketplacePackage:
        """标记为弃用"""
        pkg = self._get_or_raise(package_id)
        pkg.status = PackageStatus.DEPRECATED
        pkg.updated_at = datetime.now()
        return pkg

    async def delete_package(self, package_id: str) -> None:
        """物理删除"""
        pkg = self._get_or_raise(package_id)
        del self._packages[package_id]
        if pkg.name in self._by_name:
            del self._by_name[pkg.name]
        if pkg.package_id in self._by_type.get(pkg.package_type, set()):
            self._by_type[pkg.package_type].discard(pkg.package_id)
        self._unindex_categories(pkg)
        self._unindex_tags(pkg)

    # ── 版本管理 ────────────────────────────────────────────────────────────

    async def _add_version(self, package: MarketplacePackage, version: str):
        """添加新版本记录"""
        # 检查不重复
        for v in package.versions:
            if v.version == version:
                return
        package.versions.append(PackageVersion(
            version=version,
            release_date=datetime.now(),
            changelog=f"Version {version}",
        ))

    async def add_version(
        self, package_id: str, version: PackageVersion
    ) -> MarketplacePackage:
        """显式添加版本"""
        pkg = self._get_or_raise(package_id)
        version.release_date = version.release_date or datetime.now()
        # 去重
        existing = [v for v in pkg.versions if v.version == version.version]
        if existing:
            # 更新已有版本
            idx = pkg.versions.index(existing[0])
            pkg.versions[idx] = version
        else:
            pkg.versions.append(version)
        pkg.updated_at = datetime.now()
        return pkg

    async def get_versions(self, package_id: str) -> list[PackageVersion]:
        """获取所有版本"""
        pkg = self._get_or_raise(package_id)
        return list(pkg.versions)

    # ── 查询 ────────────────────────────────────────────────────────────────

    def get_package(self, package_id: str) -> MarketplacePackage | None:
        return self._packages.get(package_id)

    def get_by_name(self, name: str) -> MarketplacePackage | None:
        pid = self._by_name.get(name)
        if pid:
            return self._packages.get(pid)
        return None

    def list_packages(
        self,
        package_type: PackageType | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        status: PackageStatus | None = None,
        author: str | None = None,
        sort_by: str = "updated",
        sort_order: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> list[MarketplacePackage]:
        """列表查询，支持多维度筛选"""
        results: list[MarketplacePackage] = []

        for pkg in self._packages.values():
            if status is not None and pkg.status != status:
                continue
            if package_type is not None and pkg.package_type != package_type:
                continue
            if category is not None and pkg.category != category:
                continue
            if author is not None and pkg.author != author:
                continue
            if tags:
                pkg_tags = set(pkg.tags)
                if not all(t in pkg_tags for t in tags):
                    continue
            results.append(pkg)

        # 排序
        reverse = sort_order == "desc"
        if sort_by == "downloads":
            results.sort(key=lambda p: p.download_count, reverse=reverse)
        elif sort_by == "rating":
            results.sort(key=lambda p: p.average_rating, reverse=reverse)
        elif sort_by == "name":
            results.sort(key=lambda p: p.name, reverse=reverse)
        else:  # "updated"
            results.sort(key=lambda p: p.updated_at, reverse=reverse)

        return results[offset:offset + limit]

    def count_packages(self, **filters) -> int:
        return len(self.list_packages(limit=100000, **filters))

    # ── 统计 ────────────────────────────────────────────────────────────────

    async def get_stats(self) -> MarketplaceStats:
        """获取市场统计"""
        all_pkgs = list(self._packages.values())
        published = [p for p in all_pkgs if p.status == PackageStatus.PUBLISHED]
        deprecated = [p for p in all_pkgs if p.status == PackageStatus.DEPRECATED]

        by_type: dict[str, int] = {}
        by_category: dict[str, int] = {}
        for p in published:
            by_type[p.package_type.value] = by_type.get(p.package_type.value, 0) + 1
            by_category[p.category] = by_category.get(p.category, 0) + 1

        # top 下载榜
        top_down = sorted(published, key=lambda p: p.download_count, reverse=True)[:10]
        top_downloaded = [
            {"package_id": p.package_id, "name": p.name, "download_count": p.download_count}
            for p in top_down
        ]

        # top 评分榜（至少 3 个评分）
        rated = [p for p in published if p.rating_count >= 3]
        top_rated = sorted(rated, key=lambda p: p.average_rating, reverse=True)[:10]
        top_rated_list = [
            {"package_id": p.package_id, "name": p.name, "average_rating": p.average_rating,
             "rating_count": p.rating_count}
            for p in top_rated
        ]

        return MarketplaceStats(
            total_packages=len(all_pkgs),
            total_downloads=sum(p.download_count for p in all_pkgs),
            total_installs=sum(p.install_count for p in all_pkgs),
            published_packages=len(published),
            deprecrated_packages=len(deprecated),
            by_type=by_type,
            by_category=by_category,
            top_downloaded=top_downloaded,
            top_rated=top_rated_list,
        )

    # ── 钩子 ────────────────────────────────────────────────────────────────

    def on_publish(self, callback):
        """注册发布/更新回调 (coroutine function)"""
        self._on_publish_hooks.append(callback)

    def on_unpublish(self, callback):
        """注册下架回调"""
        self._on_unpublish_hooks.append(callback)

    async def _fire_publish_hooks(self, pkg: MarketplacePackage, action: str):
        for hook in self._on_publish_hooks:
            try:
                await hook(pkg, action)
            except Exception:
                pass

    async def _fire_unpublish_hooks(self, pkg: MarketplacePackage):
        for hook in self._on_unpublish_hooks:
            try:
                await hook(pkg)
            except Exception:
                pass

    # ── 内部辅助 ────────────────────────────────────────────────────────────

    def _get_or_raise(self, package_id: str) -> MarketplacePackage:
        pkg = self._packages.get(package_id)
        if pkg is None:
            raise KeyError(f"Package '{package_id}' not found")
        return pkg

    def _index_categories(self, package: MarketplacePackage):
        if package.category not in self._by_category:
            self._by_category[package.category] = set()
        self._by_category[package.category].add(package.package_id)

    def _index_tags(self, package: MarketplacePackage):
        for tag in package.tags:
            if tag not in self._by_tag:
                self._by_tag[tag] = set()
            self._by_tag[tag].add(package.package_id)

    def _unindex_categories(self, package: MarketplacePackage):
        if package.category in self._by_category:
            self._by_category[package.category].discard(package.package_id)

    def _unindex_tags(self, package: MarketplacePackage):
        for tag in package.tags:
            if tag in self._by_tag:
                self._by_tag[tag].discard(package.package_id)
