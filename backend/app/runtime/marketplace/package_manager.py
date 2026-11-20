"""
W29-30: AI Marketplace — 能力包管理器

管理本地安装/卸载/更新/版本锁定。模拟本地文件系统安装。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.runtime.marketplace.models import (
    InstallRecord,
    InstallStatus,
    MarketplacePackage,
    PackageType,
)


class PackageManager:
    """能力包安装管理器

    管理本地已安装的能力包，提供 install / uninstall / update / list / check_updates。
    安装状态保存在内存中（生产环境可扩展为 SQLite/文件系统）。
    """

    def __init__(self, install_root: str = "/var/lib/marketplace/packages"):
        self._install_root = install_root
        self._installed: dict[str, InstallRecord] = {}   # package_id -> record
        self._by_name: dict[str, str] = {}               # name -> package_id

    # ── 安装 ────────────────────────────────────────────────────────────────

    async def install(
        self,
        package: MarketplacePackage,
        version: str | None = None,
        auto_update: bool = False,
        config_override: dict | None = None,
    ) -> InstallRecord:
        """安装能力包

        若已安装同版本则跳过，不同版本则更新。
        """
        target_version = version or package.version

        # 检查是否已安装相同版本
        if package.package_id in self._installed:
            existing = self._installed[package.package_id]
            if existing.version == target_version and existing.status == InstallStatus.INSTALLED:
                return existing

        # 校验版本存在
        version_found = any(v.version == target_version for v in package.versions)
        if not version_found and package.version != target_version:
            raise ValueError(
                f"Version '{target_version}' not found for package '{package.name}'"
            )

        install_id = None
        if package.package_id in self._installed:
            install_id = self._installed[package.package_id].install_id

        record = InstallRecord(
            install_id=install_id or f"inst-{package.package_id[:8]}",
            package_id=package.package_id,
            package_name=package.name,
            package_type=package.package_type,
            version=target_version,
            install_path=f"{self._install_root}/{package.name}/{target_version}",
            status=InstallStatus.INSTALLING,
            auto_update=auto_update,
            config_override=config_override or {},
        )

        # 模拟安装过程
        record.status = InstallStatus.INSTALLED
        record.installed_at = datetime.now()
        record.updated_at = datetime.now()
        self._installed[package.package_id] = record
        self._by_name[package.name] = package.package_id
        package.install_count += 1
        return record

    # ── 卸载 ────────────────────────────────────────────────────────────────

    async def uninstall(self, package_id: str) -> InstallRecord:
        """卸载能力包"""
        record = self._installed.pop(package_id, None)
        if record is None:
            raise KeyError(f"Package '{package_id}' is not installed")

        if record.package_name in self._by_name:
            del self._by_name[record.package_name]

        record.status = InstallStatus.UNINSTALLED
        record.updated_at = datetime.now()
        return record

    # ── 更新 ────────────────────────────────────────────────────────────────

    async def update(
        self, package_id: str, package: MarketplacePackage, version: str | None = None
    ) -> InstallRecord:
        """更新到新版本"""
        target_version = version or package.version
        current = self.get_installed(package_id)
        if current and current.version == target_version:
            return current
        return await self.install(package, target_version)

    async def check_updates(
        self, registry_packages: dict[str, MarketplacePackage]
    ) -> list[dict]:
        """检查已安装包的更新

        Returns:
            [{"package_id": ..., "current_version": ..., "latest_version": ...}]
        """
        updates = []
        for pkg_id, record in self._installed.items():
            if record.status != InstallStatus.INSTALLED:
                continue
            upstream = registry_packages.get(pkg_id)
            if upstream and upstream.version != record.version:
                updates.append({
                    "package_id": pkg_id,
                    "package_name": record.package_name,
                    "current_version": record.version,
                    "latest_version": upstream.version,
                })
        return updates

    async def update_all(
        self, registry_packages: dict[str, MarketplacePackage]
    ) -> list[InstallRecord]:
        """批量更新所有可升级的包"""
        updates = await self.check_updates(registry_packages)
        results = []
        for item in updates:
            pkg = registry_packages.get(item["package_id"])
            if pkg:
                record = await self.update(item["package_id"], pkg)
                results.append(record)
        return results

    # ── 查询 ────────────────────────────────────────────────────────────────

    def get_installed(self, package_id: str) -> InstallRecord | None:
        return self._installed.get(package_id)

    def is_installed(self, package_id: str) -> bool:
        record = self._installed.get(package_id)
        return record is not None and record.status == InstallStatus.INSTALLED

    def list_installed(
        self,
        package_type: PackageType | None = None,
    ) -> list[InstallRecord]:
        """列出已安装的能力包"""
        results = [r for r in self._installed.values()
                   if r.status == InstallStatus.INSTALLED]
        if package_type is not None:
            results = [r for r in results if r.package_type == package_type]
        results.sort(key=lambda r: r.installed_at, reverse=True)
        return results

    def get_installed_count(self) -> int:
        return sum(1 for r in self._installed.values()
                   if r.status == InstallStatus.INSTALLED)
