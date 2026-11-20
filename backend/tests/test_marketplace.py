"""
W29-30: AI Marketplace — 测试套件

覆盖:
- 数据模型 (PackageVersion / MarketplacePackage / PackageRating / SearchQuery / InstallRecord)
- MarketplaceRegistry (发布/下架/版本/统计/列表)
- PackageManager (安装/卸载/更新/检查更新)
- SearchEngine (索引/搜索/建议/TF-IDF)
- RatingSystem (评分/分布/聚合)
- 集成测试 (Registry + SearchEngine + PackageManager + RatingSystem)
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from app.runtime.marketplace.models import (
    InstallRecord,
    InstallStatus,
    LicenseType,
    MarketplacePackage,
    MarketplaceStats,
    PackageRating,
    PackageStatus,
    PackageType,
    PackageVersion,
    ReviewRecord,
    ReviewStatus,
    SearchQuery,
    SearchResult,
)
from app.runtime.marketplace.package_manager import PackageManager
from app.runtime.marketplace.rating import RatingSystem
from app.runtime.marketplace.registry import MarketplaceRegistry
from app.runtime.marketplace.search_engine import SearchEngine


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_package(
    name: str = "test-skill",
    display_name: str = "Test Skill",
    package_type: PackageType = PackageType.SKILL,
    description: str = "A test skill package",
    tags: list[str] | None = None,
    category: str = "general",
    version: str = "1.0.0",
    status: PackageStatus = PackageStatus.PUBLISHED,
) -> MarketplacePackage:
    """创建测试用能力包"""
    pkg = MarketplacePackage(
        name=name,
        display_name=display_name,
        package_type=package_type,
        status=status,
        version=version,
        description=description,
        tags=tags or ["test"],
        category=category,
        author="test-author",
        entry_point=f"skill.{name}.main",
    )
    pkg.versions.append(PackageVersion(
        version=version,
        release_date=datetime.now(),
        changelog=f"Initial release of {name}",
    ))
    return pkg


def make_packages(count: int, prefix: str = "pkg", base_type: PackageType = PackageType.SKILL) -> list[MarketplacePackage]:
    """批量创建测试包"""
    return [
        make_package(
            name=f"{prefix}-{i}",
            display_name=f"{prefix.upper()} {i}",
            package_type=base_type,
            tags=["test", f"tag-{i % 3}"],
            version=f"1.{i}.0",
        )
        for i in range(count)
    ]


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def registry():
    """市场注册中心 fixture"""
    reg = MarketplaceRegistry()
    yield reg


@pytest_asyncio.fixture
async def populated_registry(registry):
    """预填充的注册中心（10个发布包）"""
    packages = make_packages(10)
    for pkg in packages:
        pkg.status = PackageStatus.PUBLISHED
        await registry.publish(pkg)
    return registry


@pytest_asyncio.fixture
async def package_manager():
    """安装管理器 fixture"""
    return PackageManager()


@pytest_asyncio.fixture
async def search_engine():
    """搜索引擎 fixture"""
    return SearchEngine()


@pytest_asyncio.fixture
async def rating_system():
    """评分系统 fixture"""
    return RatingSystem()


# ─── 模型测试 ────────────────────────────────────────────────────────────────

class TestPackageModels:
    """数据模型测试"""

    def test_package_version_defaults(self):
        """PackageVersion 默认值"""
        pv = PackageVersion(version="1.0.0")
        assert pv.version == "1.0.0"
        assert pv.changelog == ""
        assert pv.requires_models == []
        assert pv.requires_permissions == []
        assert pv.min_runtime_version == "1.0.0"
        assert pv.dependencies == {}

    def test_package_version_with_deps(self):
        """PackageVersion 含依赖"""
        pv = PackageVersion(
            version="2.0.0",
            requires_models=["gpt-4", "claude-3"],
            dependencies={"skill-base": ">=1.0.0"},
            package_size_bytes=4096,
            checksum_sha256="abc123",
        )
        assert len(pv.requires_models) == 2
        assert pv.dependencies["skill-base"] == ">=1.0.0"
        assert pv.package_size_bytes == 4096

    def test_marketplace_package_defaults(self):
        """MarketplacePackage 默认值"""
        pkg = MarketplacePackage(name="test-pkg")
        assert pkg.package_id != ""
        assert pkg.package_type == PackageType.SKILL
        assert pkg.status == PackageStatus.DRAFT
        assert pkg.version == "0.1.0"
        assert pkg.tags == []
        assert pkg.download_count == 0
        assert pkg.average_rating == 0.0

    def test_marketplace_package_is_published(self):
        """发布状态检测"""
        pkg = make_package(status=PackageStatus.PUBLISHED)
        assert pkg.is_published is True
        pkg.status = PackageStatus.DRAFT
        assert pkg.is_published is False

    def test_marketplace_package_to_search_doc(self):
        """搜索文档转换"""
        pkg = make_package(name="search-test", display_name="Search Test")
        doc = pkg.to_search_doc()
        assert doc["package_id"] == pkg.package_id
        assert doc["name"] == "search-test"
        assert doc["display_name"] == "Search Test"
        assert doc["package_type"] == "skill"
        assert "test" in doc["tags"]

    def test_package_rating_fields(self):
        """PackageRating 字段"""
        rating = PackageRating(
            package_id="pkg-1",
            user_id="user-1",
            score=4.5,
            title="Great!",
            review="Very useful skill",
        )
        assert rating.score == 4.5
        assert rating.user_id == "user-1"
        assert rating.helpful_count == 0

    def test_search_query_defaults(self):
        """SearchQuery 默认值"""
        sq = SearchQuery()
        assert sq.keywords == ""
        assert sq.page == 1
        assert sq.page_size == 20
        assert sq.sort_by == "relevance"
        assert sq.offset == 0

    def test_search_query_pagination(self):
        """SearchQuery 分页计算"""
        sq = SearchQuery(page=3, page_size=10)
        assert sq.offset == 20

    def test_install_record_fields(self):
        """InstallRecord 字段"""
        record = InstallRecord(
            package_id="pkg-1",
            package_name="test-pkg",
            version="1.0.0",
            install_path="/tmp/test",
            auto_update=True,
        )
        assert record.status == InstallStatus.INSTALLING
        assert record.auto_update is True

    def test_marketplace_stats_defaults(self):
        """MarketplaceStats 默认值"""
        stats = MarketplaceStats()
        assert stats.total_packages == 0
        assert stats.total_downloads == 0
        assert stats.by_type == {}
        assert stats.top_downloaded == []

    def test_package_status_properties(self):
        """PackageStatus 可用性/可安装性"""
        assert PackageStatus.PUBLISHED.is_available is True
        assert PackageStatus.PUBLISHED.is_installable is True
        assert PackageStatus.DEPRECATED.is_available is True
        assert PackageStatus.DEPRECATED.is_installable is False
        assert PackageStatus.DRAFT.is_available is False
        assert PackageStatus.ARCHIVED.is_available is False

    def test_package_type_values(self):
        """PackageType 枚举值"""
        assert PackageType.SKILL.value == "skill"
        assert PackageType.AGENT.value == "agent"
        assert PackageType.WORKFLOW.value == "workflow"

    def test_review_record(self):
        """ReviewRecord"""
        review = ReviewRecord(
            package_id="pkg-1",
            reviewer_id="admin-1",
            comments="LGTM",
        )
        assert review.status == ReviewStatus.PENDING
        assert review.issues == []


# ─── MarketplaceRegistry 测试 ────────────────────────────────────────────────

class TestMarketplaceRegistry:
    """市场注册中心测试"""

    @pytest.mark.asyncio
    async def test_publish_new_package(self, registry):
        """发布新包"""
        pkg = make_package(name="new-skill")
        result = await registry.publish(pkg)
        assert result.package_id == pkg.package_id
        assert result.status == PackageStatus.PUBLISHED
        assert registry.get_package(pkg.package_id) is not None

    @pytest.mark.asyncio
    async def test_publish_duplicate_name(self, registry):
        """同名发布更新"""
        pkg1 = make_package(name="same-name", version="1.0.0")
        await registry.publish(pkg1)
        pkg2 = make_package(name="same-name", version="2.0.0")
        pkg2.package_id = pkg1.package_id  # same ID = update
        result = await registry.publish(pkg2)
        assert result.version == "2.0.0"
        assert len(registry._packages) == 1

    @pytest.mark.asyncio
    async def test_publish_different_id_same_name_raises(self, registry):
        """不同 ID 同名包抛异常"""
        pkg1 = make_package(name="conflict-name")
        await registry.publish(pkg1)
        pkg2 = make_package(name="conflict-name")
        with pytest.raises(ValueError, match="already registered"):
            await registry.publish(pkg2)

    @pytest.mark.asyncio
    async def test_unpublish_package(self, registry):
        """下架"""
        pkg = make_package()
        await registry.publish(pkg)
        result = await registry.unpublish(pkg.package_id)
        assert result.status == PackageStatus.ARCHIVED

    @pytest.mark.asyncio
    async def test_deprecate_package(self, registry):
        """弃用"""
        pkg = make_package()
        await registry.publish(pkg)
        result = await registry.deprecate(pkg.package_id)
        assert result.status == PackageStatus.DEPRECATED

    @pytest.mark.asyncio
    async def test_delete_package(self, registry):
        """物理删除"""
        pkg = make_package()
        await registry.publish(pkg)
        await registry.delete_package(pkg.package_id)
        assert registry.get_package(pkg.package_id) is None

    @pytest.mark.asyncio
    async def test_get_by_name(self, registry):
        """按名称查找"""
        pkg = make_package(name="find-by-name")
        await registry.publish(pkg)
        found = registry.get_by_name("find-by-name")
        assert found is not None
        assert found.package_id == pkg.package_id

    @pytest.mark.asyncio
    async def test_get_by_name_not_found(self, registry):
        """按名称查找不存在"""
        assert registry.get_by_name("no-such-pkg") is None

    @pytest.mark.asyncio
    async def test_add_version(self, registry):
        """添加版本"""
        pkg = make_package(version="1.0.0")
        await registry.publish(pkg)
        await registry.add_version(pkg.package_id, PackageVersion(
            version="2.0.0",
            changelog="Major update",
        ))
        versions = await registry.get_versions(pkg.package_id)
        assert len(versions) == 2
        assert any(v.version == "2.0.0" for v in versions)

    @pytest.mark.asyncio
    async def test_add_duplicate_version_updates(self, registry):
        """重复版本会更新"""
        pkg = make_package(version="1.0.0")
        await registry.publish(pkg)
        v1 = PackageVersion(version="1.0.0", changelog="Updated")
        await registry.add_version(pkg.package_id, v1)
        versions = await registry.get_versions(pkg.package_id)
        assert len(versions) == 1
        assert versions[0].changelog == "Updated"

    @pytest.mark.asyncio
    async def test_get_versions_not_found_raises(self, registry):
        """获取不存在包的版本"""
        with pytest.raises(KeyError, match="not found"):
            await registry.get_versions("no-such-id")

    @pytest.mark.asyncio
    async def test_list_packages_all(self, populated_registry):
        """列出所有包"""
        results = populated_registry.list_packages()
        assert len(results) == 10

    @pytest.mark.asyncio
    async def test_list_packages_by_type(self, registry):
        """按类型筛选"""
        pkg_skill = make_package(name="s1", package_type=PackageType.SKILL)
        pkg_agent = make_package(name="a1", package_type=PackageType.AGENT)
        await registry.publish(pkg_skill)
        await registry.publish(pkg_agent)
        skills = registry.list_packages(package_type=PackageType.SKILL)
        assert len(skills) == 1
        assert skills[0].package_type == PackageType.SKILL

    @pytest.mark.asyncio
    async def test_list_packages_by_category(self, registry):
        """按分类筛选"""
        pkg = make_package(category="dev-tools")
        await registry.publish(pkg)
        results = registry.list_packages(category="dev-tools")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_list_packages_by_tags(self, registry):
        """按标签筛选"""
        pkg = make_package(tags=["python", "data"])
        await registry.publish(pkg)
        results = registry.list_packages(tags=["python"])
        assert len(results) == 1
        results2 = registry.list_packages(tags=["python", "data"])
        assert len(results2) == 1

    @pytest.mark.asyncio
    async def test_list_packages_sort_downloads(self, populated_registry):
        """按下载量排序"""
        # 设置不同下载量
        pkgs = list(populated_registry._packages.values())
        for i, p in enumerate(pkgs):
            p.download_count = i * 10
        results = populated_registry.list_packages(sort_by="downloads", sort_order="desc")
        assert results[0].download_count >= results[-1].download_count

    @pytest.mark.asyncio
    async def test_count_packages(self, populated_registry):
        """统计数量"""
        assert populated_registry.count_packages() == 10

    @pytest.mark.asyncio
    async def test_publish_updates_timestamp(self, registry):
        """发布后 updated_at 更新"""
        pkg = make_package()
        await registry.publish(pkg)
        ts = pkg.updated_at
        pkg2 = make_package(name=pkg.name, version="2.0.0")
        pkg2.package_id = pkg.package_id
        result = await registry.publish(pkg2)
        assert result.updated_at >= ts

    @pytest.mark.asyncio
    async def test_publish_sets_published_at(self, registry):
        """首次发布设置 published_at"""
        pkg = make_package()
        await registry.publish(pkg)
        assert pkg.published_at is not None

    @pytest.mark.asyncio
    async def test_get_stats(self, populated_registry):
        """市场统计"""
        stats = await populated_registry.get_stats()
        assert stats.total_packages == 10
        assert stats.published_packages == 10
        assert isinstance(stats, MarketplaceStats)

    @pytest.mark.asyncio
    async def test_delete_with_index_cleanup(self, registry):
        """删除包时清理索引"""
        pkg = make_package(name="to-delete")
        await registry.publish(pkg)
        await registry.delete_package(pkg.package_id)
        assert registry.get_by_name("to-delete") is None
        assert registry.get_package(pkg.package_id) is None


# ─── PackageManager 测试 ─────────────────────────────────────────────────────

class TestPackageManager:
    """安装管理器测试"""

    @pytest.mark.asyncio
    async def test_install_package(self, package_manager):
        """安装包"""
        pkg = make_package()
        record = await package_manager.install(pkg)
        assert record.status == InstallStatus.INSTALLED
        assert record.package_id == pkg.package_id
        assert record.package_name == pkg.name

    @pytest.mark.asyncio
    async def test_install_specific_version(self, package_manager):
        """安装指定版本"""
        pkg = make_package()
        pkg.versions.append(PackageVersion(version="2.0.0"))
        record = await package_manager.install(pkg, version="2.0.0")
        assert record.version == "2.0.0"

    @pytest.mark.asyncio
    async def test_install_nonexistent_version(self, package_manager):
        """安装不存在的版本"""
        pkg = make_package()
        with pytest.raises(ValueError, match="not found"):
            await package_manager.install(pkg, version="99.0.0")

    @pytest.mark.asyncio
    async def test_install_duplicate_returns_existing(self, package_manager):
        """重复安装返回已有记录"""
        pkg = make_package()
        r1 = await package_manager.install(pkg)
        r2 = await package_manager.install(pkg)
        assert r1.install_id == r2.install_id

    @pytest.mark.asyncio
    async def test_uninstall_package(self, package_manager):
        """卸载"""
        pkg = make_package()
        await package_manager.install(pkg)
        record = await package_manager.uninstall(pkg.package_id)
        assert record.status == InstallStatus.UNINSTALLED

    @pytest.mark.asyncio
    async def test_uninstall_not_installed_raises(self, package_manager):
        """卸载未安装的包"""
        with pytest.raises(KeyError, match="not installed"):
            await package_manager.uninstall("no-such-id")

    @pytest.mark.asyncio
    async def test_is_installed(self, package_manager):
        """检查安装状态"""
        pkg = make_package()
        assert not package_manager.is_installed(pkg.package_id)
        await package_manager.install(pkg)
        assert package_manager.is_installed(pkg.package_id)

    @pytest.mark.asyncio
    async def test_update_package(self, package_manager):
        """更新包"""
        pkg = make_package()
        await package_manager.install(pkg)
        pkg.versions.append(PackageVersion(version="2.0.0"))
        pkg.version = "2.0.0"
        record = await package_manager.update(pkg.package_id, pkg)
        assert record.version == "2.0.0"

    @pytest.mark.asyncio
    async def test_list_installed(self, package_manager):
        """列出已安装"""
        for i in range(3):
            pkg = make_package(name=f"pkg-{i}")
            await package_manager.install(pkg)
        records = package_manager.list_installed()
        assert len(records) == 3

    @pytest.mark.asyncio
    async def test_list_installed_by_type(self, package_manager):
        """按类型列出"""
        pkg_s = make_package(name="skill-1", package_type=PackageType.SKILL)
        pkg_a = make_package(name="agent-1", package_type=PackageType.AGENT)
        await package_manager.install(pkg_s)
        await package_manager.install(pkg_a)
        assert len(package_manager.list_installed(PackageType.SKILL)) == 1
        assert len(package_manager.list_installed(PackageType.AGENT)) == 1

    @pytest.mark.asyncio
    async def test_check_updates(self, package_manager):
        """检查更新"""
        pkg = make_package(version="1.0.0")
        await package_manager.install(pkg)
        # 上游有新版本
        pkg.version = "2.0.0"
        registry_packages = {pkg.package_id: pkg}
        updates = await package_manager.check_updates(registry_packages)
        assert len(updates) == 1
        assert updates[0]["current_version"] == "1.0.0"
        assert updates[0]["latest_version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_check_updates_no_changes(self, package_manager):
        """无更新"""
        pkg = make_package(version="1.0.0")
        await package_manager.install(pkg)
        registry_packages = {pkg.package_id: pkg}
        updates = await package_manager.check_updates(registry_packages)
        assert len(updates) == 0

    @pytest.mark.asyncio
    async def test_update_all(self, package_manager):
        """批量更新"""
        pkgs = []
        for i in range(3):
            pkg = make_package(name=f"update-pkg-{i}", version="1.0.0")
            await package_manager.install(pkg)
            pkg.version = "2.0.0"
            pkgs.append(pkg)
        registry_packages = {p.package_id: p for p in pkgs}
        results = await package_manager.update_all(registry_packages)
        assert len(results) == 3
        assert all(r.version == "2.0.0" for r in results)

    @pytest.mark.asyncio
    async def test_get_installed_count(self, package_manager):
        """已安装计数"""
        assert package_manager.get_installed_count() == 0
        pkg = make_package()
        await package_manager.install(pkg)
        assert package_manager.get_installed_count() == 1

    @pytest.mark.asyncio
    async def test_install_path_format(self, package_manager):
        """安装路径格式"""
        pkg = make_package(name="my-skill", version="1.2.3")
        record = await package_manager.install(pkg)
        assert "my-skill" in record.install_path
        assert "1.2.3" in record.install_path

    @pytest.mark.asyncio
    async def test_uninstall_clears_by_name(self, package_manager):
        """卸载后按名称查不到"""
        pkg = make_package(name="cleanup-test")
        await package_manager.install(pkg)
        await package_manager.uninstall(pkg.package_id)
        assert not package_manager.is_installed(pkg.package_id)


# ─── SearchEngine 测试 ───────────────────────────────────────────────────────

class TestSearchEngine:
    """搜索引擎测试"""

    @pytest.mark.asyncio
    async def test_index_package(self, search_engine):
        """索引包"""
        pkg = make_package()
        await search_engine.index(pkg)
        assert search_engine.get_index_count() == 1

    @pytest.mark.asyncio
    async def test_deindex_package(self, search_engine):
        """从索引中移除"""
        pkg = make_package()
        await search_engine.index(pkg)
        await search_engine.deindex(pkg.package_id)
        assert search_engine.get_index_count() == 0

    @pytest.mark.asyncio
    async def test_search_by_keywords(self, search_engine):
        """关键词搜索"""
        pkgs = [
            make_package(name="python-http", tags=["python", "http"]),
            make_package(name="node-websocket", tags=["node", "websocket"]),
            make_package(name="rust-parser", tags=["rust"]),
        ]
        registry_dict = {p.package_id: p for p in pkgs}
        for p in pkgs:
            await search_engine.index(p)

        query = SearchQuery(keywords="python")
        results = await search_engine.search(query, registry_dict)
        assert len(results) > 0
        assert results[0].name == "python-http"

    @pytest.mark.asyncio
    async def test_search_no_keywords(self, search_engine):
        """无关键词搜索（纯筛选）"""
        pkgs = make_packages(5)
        registry_dict = {p.package_id: p for p in pkgs}
        for p in pkgs:
            await search_engine.index(p)

        query = SearchQuery()
        results = await search_engine.search(query, registry_dict)
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_search_filter_by_type(self, search_engine):
        """按类型过滤"""
        agent = make_package(name="my-agent", package_type=PackageType.AGENT)
        skill = make_package(name="my-skill", package_type=PackageType.SKILL)
        registry_dict = {agent.package_id: agent, skill.package_id: skill}
        await search_engine.index(agent)
        await search_engine.index(skill)

        query = SearchQuery(keywords="my", package_type=PackageType.AGENT)
        results = await search_engine.search(query, registry_dict)
        assert len(results) == 1
        assert results[0].package_type == PackageType.AGENT

    @pytest.mark.asyncio
    async def test_search_sort_by_downloads(self, search_engine):
        """按下载量排序"""
        pkgs = make_packages(5)
        for i, p in enumerate(pkgs):
            p.download_count = i * 10
        registry_dict = {p.package_id: p for p in pkgs}
        for p in pkgs:
            await search_engine.index(p)

        query = SearchQuery(keywords="pkg", sort_by="downloads", sort_order="desc")
        results = await search_engine.search(query, registry_dict)
        assert results[0].download_count >= results[-1].download_count

    @pytest.mark.asyncio
    async def test_search_pagination(self, search_engine):
        """分页"""
        pkgs = make_packages(30)
        registry_dict = {p.package_id: p for p in pkgs}
        for p in pkgs:
            await search_engine.index(p)

        query = SearchQuery(keywords="pkg", page=1, page_size=10)
        results = await search_engine.search(query, registry_dict)
        assert len(results) == 10

    @pytest.mark.asyncio
    async def test_search_min_rating(self, search_engine):
        """最低评分过滤"""
        pkg = make_package()
        pkg.average_rating = 4.5
        registry_dict = {pkg.package_id: pkg}
        await search_engine.index(pkg)

        query = SearchQuery(keywords="test", min_rating=4.0)
        results = await search_engine.search(query, registry_dict)
        assert len(results) == 1

        query2 = SearchQuery(keywords="test", min_rating=4.8)
        results2 = await search_engine.search(query2, registry_dict)
        assert len(results2) == 0

    @pytest.mark.asyncio
    async def test_suggest(self, search_engine):
        """搜索建议"""
        for i in range(5):
            pkg = make_package(name=f"data-tool-{i}", display_name=f"Data Tool {i}")
            await search_engine.index(pkg)

        suggestions = await search_engine.suggest("data")
        assert len(suggestions) > 0

    @pytest.mark.asyncio
    async def test_suggest_limit(self, search_engine):
        """建议数量限制"""
        for i in range(20):
            pkg = make_package(name=f"tool-{i}", display_name=f"Tool {i}")
            await search_engine.index(pkg)

        suggestions = await search_engine.suggest("tool", limit=5)
        assert len(suggestions) <= 5

    @pytest.mark.asyncio
    async def test_reindex_all(self, search_engine):
        """重建全部索引"""
        pkgs = make_packages(10)
        for p in pkgs:
            await search_engine.index(p)
        assert search_engine.get_index_count() == 10

        new_pkgs = make_packages(5, prefix="new")
        await search_engine.reindex_all(new_pkgs)
        assert search_engine.get_index_count() == 5

    @pytest.mark.asyncio
    async def test_search_chinese_keywords(self, search_engine):
        """中文关键词搜索"""
        pkg = make_package(
            name="code-reviewer",
            display_name="代码审查工具",
            description="用于代码审查和质量检测",
            tags=["代码", "审查", "质量"],
        )
        registry_dict = {pkg.package_id: pkg}
        await search_engine.index(pkg)

        query = SearchQuery(keywords="代码审查")
        results = await search_engine.search(query, registry_dict)
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_search_by_tags_filter(self, search_engine):
        """标签筛选"""
        pkg = make_package(tags=["python", "async"])
        await search_engine.index(pkg)
        registry_dict = {pkg.package_id: pkg}

        query = SearchQuery(keywords="test", tags=["python"])
        results = await search_engine.search(query, registry_dict)
        assert len(results) == 1

        query2 = SearchQuery(keywords="test", tags=["nonexistent"])
        results2 = await search_engine.search(query2, registry_dict)
        assert len(results2) == 0

    @pytest.mark.asyncio
    async def test_tokenize_mixed_language(self, search_engine):
        """混合中英文分词"""
        tokens = search_engine._tokenize("hello world 你好世界 test_123")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test_123" in tokens
        assert "你" in tokens
        assert "好" in tokens
        assert "世" in tokens
        assert "界" in tokens

    @pytest.mark.asyncio
    async def test_empty_index_search_returns_empty(self, search_engine):
        """空索引搜索返回空"""
        query = SearchQuery(keywords="nothing")
        registry_dict = {}
        results = await search_engine.search(query, registry_dict)
        assert len(results) == 0


# ─── RatingSystem 测试 ───────────────────────────────────────────────────────

class TestRatingSystem:
    """评分系统测试"""

    @pytest.mark.asyncio
    async def test_submit_rating(self, rating_system):
        """提交评分"""
        pkg = make_package()
        rating = await rating_system.submit_rating(pkg, "user-1", 4.5)
        assert rating.score == 4.5
        assert pkg.average_rating == 4.5
        assert pkg.rating_count == 1

    @pytest.mark.asyncio
    async def test_submit_multiple_ratings_recalc(self, rating_system):
        """多个评分后聚合更新"""
        pkg = make_package()
        await rating_system.submit_rating(pkg, "u1", 5.0)
        await rating_system.submit_rating(pkg, "u2", 3.0)
        assert pkg.rating_count == 2
        assert pkg.average_rating == 4.0

    @pytest.mark.asyncio
    async def test_update_existing_rating(self, rating_system):
        """更新已有评分"""
        pkg = make_package()
        r1 = await rating_system.submit_rating(pkg, "user-1", 3.0)
        r2 = await rating_system.submit_rating(pkg, "user-1", 5.0)
        assert r1.rating_id == r2.rating_id  # 同一用户同一条
        assert r2.score == 5.0
        assert pkg.average_rating == 5.0

    @pytest.mark.asyncio
    async def test_submit_invalid_score_raises(self, rating_system):
        """无效评分抛异常"""
        pkg = make_package()
        with pytest.raises(ValueError, match="between"):
            await rating_system.submit_rating(pkg, "u1", 0.5)
        with pytest.raises(ValueError, match="between"):
            await rating_system.submit_rating(pkg, "u1", 6.0)
        with pytest.raises(ValueError, match="0.5 increments"):
            await rating_system.submit_rating(pkg, "u1", 3.7)

    @pytest.mark.asyncio
    async def test_delete_rating(self, rating_system):
        """删除评分"""
        pkg = make_package()
        rating = await rating_system.submit_rating(pkg, "u1", 4.0)
        result = await rating_system.delete_rating(rating.rating_id, pkg)
        assert result is True
        assert pkg.rating_count == 0
        assert pkg.average_rating == 0.0

    @pytest.mark.asyncio
    async def test_delete_nonexistent_rating(self, rating_system):
        """删除不存在的评分"""
        pkg = make_package()
        result = await rating_system.delete_rating("no-such-id", pkg)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_user_rating(self, rating_system):
        """获取用户评分"""
        pkg = make_package()
        await rating_system.submit_rating(pkg, "u1", 5.0, title="Best!")
        found = rating_system.get_user_rating("u1", pkg.package_id)
        assert found is not None
        assert found.title == "Best!"

    @pytest.mark.asyncio
    async def test_get_user_rating_not_found(self, rating_system):
        """用户未评分"""
        assert rating_system.get_user_rating("u1", "pkg-1") is None

    @pytest.mark.asyncio
    async def test_get_package_ratings(self, rating_system):
        """获取包的所有评分"""
        pkg = make_package()
        for i in range(5):
            await rating_system.submit_rating(pkg, f"u{i}", 4.0)
        ratings = rating_system.get_package_ratings(pkg.package_id)
        assert len(ratings) == 5

    @pytest.mark.asyncio
    async def test_get_rating_distribution(self, rating_system):
        """评分分布"""
        pkg = make_package()
        for i in range(3):
            await rating_system.submit_rating(pkg, f"u{i}", 1.0)
        for i in range(5):
            await rating_system.submit_rating(pkg, f"uh{i}", 5.0)
        dist = rating_system.get_rating_distribution(pkg.package_id)
        assert dist[1] == 3
        assert dist[5] == 5

    @pytest.mark.asyncio
    async def test_get_package_rating_count(self, rating_system):
        """获取评分数量"""
        pkg = make_package()
        assert rating_system.get_package_rating_count(pkg.package_id) == 0
        await rating_system.submit_rating(pkg, "u1", 4.0)
        assert rating_system.get_package_rating_count(pkg.package_id) == 1

    @pytest.mark.asyncio
    async def test_get_package_average_rating_empty(self, rating_system):
        """空包评分返回 0"""
        assert rating_system.get_package_average_rating("no-such") == 0.0


# ─── 集成测试 ────────────────────────────────────────────────────────────────

class TestMarketplaceIntegration:
    """多组件集成测试"""

    @pytest.mark.asyncio
    async def test_publish_index_search(self, registry, search_engine):
        """发布→索引→搜索 完整链路"""
        pkg = make_package(name="integration-test", tags=["python", "web"])
        await registry.publish(pkg)
        await search_engine.index(pkg)

        query = SearchQuery(keywords="python web")
        results = await search_engine.search(query, registry._packages)
        assert len(results) == 1
        assert results[0].name == "integration-test"

    @pytest.mark.asyncio
    async def test_install_search_rating_flow(self, registry, search_engine, package_manager, rating_system):
        """完整用户流程：搜索→安装→评分"""
        # 1. 发布并索引
        pkg = make_package(name="awesome-tool")
        await registry.publish(pkg)
        await search_engine.index(pkg)

        # 2. 搜索找到
        query = SearchQuery(keywords="awesome")
        results = await search_engine.search(query, {pkg.package_id: pkg})
        assert len(results) == 1

        # 3. 安装
        record = await package_manager.install(pkg)
        assert record.status == InstallStatus.INSTALLED
        assert pkg.install_count == 1

        # 4. 评分
        rating = await rating_system.submit_rating(pkg, "user-1", 5.0, title="Great!")
        assert pkg.average_rating == 5.0

    @pytest.mark.asyncio
    async def test_multiple_packages_ecosystem(self, registry, search_engine, package_manager):
        """多包生态系统测试"""
        # 发布各类包
        categories = ["dev-tools", "data", "web", "ai"]
        types = [PackageType.SKILL, PackageType.AGENT, PackageType.WORKFLOW]
        pkgs = []
        for i in range(10):
            pkg = make_package(
                name=f"eco-pkg-{i}",
                category=categories[i % len(categories)],
                package_type=types[i % len(types)],
                tags=[f"tag-{i % 3}"],
            )
            await registry.publish(pkg)
            await search_engine.index(pkg)
            pkgs.append(pkg)

        # 统计
        stats = await registry.get_stats()
        assert stats.total_packages == 10

        # 分类搜索
        dev_results = registry.list_packages(category="dev-tools")
        assert len(dev_results) >= 1

        # 已安装
        for pkg in pkgs[:3]:
            await package_manager.install(pkg)
        installed = package_manager.list_installed()
        assert len(installed) == 3

    @pytest.mark.asyncio
    async def test_registry_search_hook_integration(self, registry, search_engine):
        """Registry 发布事件同步到搜索引擎"""
        pkg = make_package()
        await registry.publish(pkg)
        await search_engine.index(pkg)
        assert search_engine.get_index_count() == 1

        # 下架后搜索不可见
        await registry.unpublish(pkg.package_id)
        query = SearchQuery(keywords=pkg.name, status=PackageStatus.PUBLISHED)
        results = await search_engine.search(query, registry._packages)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_deprecate_flow(self, registry, search_engine, package_manager):
        """弃用流程测试"""
        pkg = make_package()
        await registry.publish(pkg)
        await search_engine.index(pkg)
        await package_manager.install(pkg)

        # 弃用
        await registry.deprecate(pkg.package_id)
        assert pkg.status == PackageStatus.DEPRECATED
        assert pkg.status.is_available  # 仍可见
        assert not pkg.status.is_installable  # 不可安装

        # 搜索中仍然出现（但可能标记弃用）
        query = SearchQuery(keywords=pkg.name)
        results = await search_engine.search(query, registry._packages)
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_complex_search_with_multiple_filters(self, search_engine, registry):
        """多重筛选搜索"""
        pkgs = [
            make_package("alpha-tool", category="dev", tags=["python"], package_type=PackageType.SKILL),
            make_package("beta-agent", category="dev", tags=["rust"], package_type=PackageType.AGENT),
            make_package("gamma-skill", category="web", tags=["python", "js"], package_type=PackageType.SKILL),
        ]
        for p in pkgs:
            await registry.publish(p)
            await search_engine.index(p)

        # Python + SKILL
        query = SearchQuery(keywords="tool", package_type=PackageType.SKILL, tags=["python"])
        results = await search_engine.search(query, registry._packages)
        assert all(r.package_type == PackageType.SKILL for r in results)
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_rating_recalc_on_delete(self, rating_system):
        """删除评分后重新计算"""
        pkg = make_package()
        ratings = []
        for i in range(4):
            r = await rating_system.submit_rating(pkg, f"u{i}", float(i + 2))
            ratings.append(r)
        assert pkg.rating_count == 4
        assert pkg.average_rating > 0

        # 删除一半
        for r in ratings[:2]:
            await rating_system.delete_rating(r.rating_id, pkg)
        assert pkg.rating_count == 2
        # avg 应该是剩余评分的均值 (4+5)/2 = 4.5
        assert pkg.average_rating == 4.5
