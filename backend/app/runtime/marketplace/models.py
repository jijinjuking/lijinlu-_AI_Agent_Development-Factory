"""
W29-30: AI Marketplace — 数据模型

定义 Skill / Agent / Workflow 模板市场的所有数据结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


# ─── 枚举类型 ─────────────────────────────────────────────────────────────────

class PackageType(str, Enum):
    """能力包类型"""
    SKILL = "skill"           # 技能模板
    AGENT = "agent"           # Agent 定义
    WORKFLOW = "workflow"     # 工作流模板


class PackageStatus(str, Enum):
    """能力包生命周期状态"""
    DRAFT = "draft"               # 草稿
    PENDING_REVIEW = "pending"    # 待审核
    PUBLISHED = "published"       # 已发布
    DEPRECATED = "deprecated"     # 已弃用
    ARCHIVED = "archived"         # 已归档
    REJECTED = "rejected"         # 审核未通过

    @property
    def is_available(self) -> bool:
        """是否对用户可见"""
        return self in {PackageStatus.PUBLISHED, PackageStatus.DEPRECATED}

    @property
    def is_installable(self) -> bool:
        """是否可安装"""
        return self == PackageStatus.PUBLISHED


class InstallStatus(str, Enum):
    """安装状态"""
    INSTALLED = "installed"
    INSTALLING = "installing"
    FAILED = "failed"
    UNINSTALLED = "uninstalled"


class ReviewStatus(str, Enum):
    """审核状态"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class LicenseType(str, Enum):
    """许可类型"""
    MIT = "MIT"
    APACHE_2 = "Apache-2.0"
    GPL_3 = "GPL-3.0"
    PROPRIETARY = "Proprietary"
    CC_BY_4 = "CC-BY-4.0"


# ─── 核心数据类 ──────────────────────────────────────────────────────────────

@dataclass
class PackageVersion:
    """版本信息"""
    version: str                                    # 语义化版本号，如 "1.2.3"
    release_date: datetime = field(default_factory=datetime.now)
    changelog: str = ""                             # 更新日志
    requires_models: list[str] = field(default_factory=list)   # 所需模型列表
    requires_permissions: list[str] = field(default_factory=list)  # 所需权限
    min_runtime_version: str = "1.0.0"              # 最低 Runtime 版本
    package_size_bytes: int = 0                     # 包大小
    checksum_sha256: str = ""                       # 校验和
    dependencies: dict[str, str] = field(default_factory=dict)  # name -> version


@dataclass
class MarketplacePackage:
    """市场能力包（Skill / Agent / Workflow 统一模型）"""
    package_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""                                  # 唯一名称
    display_name: str = ""                          # 展示名称
    package_type: PackageType = PackageType.SKILL
    status: PackageStatus = PackageStatus.DRAFT
    version: str = "0.1.0"                          # 当前版本
    versions: list[PackageVersion] = field(default_factory=list)

    # 元数据
    author: str = "unknown"                         # 作者
    author_email: str = ""
    description: str = ""                           # 简介（一行）
    long_description: str = ""                      # 详细说明（Markdown）
    tags: list[str] = field(default_factory=list)   # 标签
    category: str = "general"                       # 分类
    icon_url: str = ""                              # 图标 URL
    homepage_url: str = ""                          # 主页 / 仓库 URL
    license_type: LicenseType = LicenseType.MIT

    # 安装与执行定义
    entry_point: str = ""                           # 安装后入口路径
    manifest: dict[str, Any] = field(default_factory=dict)  # 能力包 manifest（业务载荷）
    config_schema: dict[str, Any] = field(default_factory=dict)  # JSON Schema 配置定义
    env_template: dict[str, str] = field(default_factory=dict)  # 环境变量模板

    # 统计
    download_count: int = 0
    install_count: int = 0
    average_rating: float = 0.0
    rating_count: int = 0

    # 时间
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    published_at: datetime | None = None

    @property
    def latest_version_info(self) -> PackageVersion | None:
        """获取最新版本信息"""
        for v in self.versions:
            if v.version == self.version:
                return v
        return None

    @property
    def is_published(self) -> bool:
        return self.status == PackageStatus.PUBLISHED

    def to_search_doc(self) -> dict[str, Any]:
        """转换为搜索引擎文档"""
        return {
            "package_id": self.package_id,
            "name": self.name,
            "display_name": self.display_name,
            "package_type": self.package_type.value,
            "description": self.description,
            "long_description": self.long_description,
            "tags": self.tags,
            "category": self.category,
            "author": self.author,
            "download_count": self.download_count,
            "average_rating": self.average_rating,
        }


@dataclass
class PackageRating:
    """用户评分与评论"""
    rating_id: str = field(default_factory=lambda: str(uuid4()))
    package_id: str = ""
    user_id: str = ""
    score: float = 0.0                              # 1.0 - 5.0
    title: str = ""                                 # 标题
    review: str = ""                                # 详细评价
    helpful_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class SearchQuery:
    """搜索查询参数"""
    keywords: str = ""                              # 搜索关键词
    package_type: PackageType | None = None         # 按类型筛选
    category: str | None = None                     # 按分类筛选
    tags: list[str] = field(default_factory=list)   # 按标签筛选
    author: str | None = None                       # 按作者筛选
    sort_by: str = "relevance"                      # 排序字段: relevance / downloads / rating / updated
    sort_order: str = "desc"                        # asc / desc
    min_rating: float = 0.0                         # 最低评分
    status: PackageStatus | None = None             # 状态过滤
    page: int = 1
    page_size: int = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


@dataclass
class SearchResult:
    """搜索结果项"""
    package_id: str
    name: str
    display_name: str
    package_type: PackageType
    description: str
    author: str
    version: str
    download_count: int
    average_rating: float
    tags: list[str] = field(default_factory=list)
    category: str = "general"
    relevance_score: float = 0.0                    # 相关性得分


@dataclass
class InstallRecord:
    """本地安装记录"""
    install_id: str = field(default_factory=lambda: str(uuid4()))
    package_id: str = ""
    package_name: str = ""
    package_type: PackageType = PackageType.SKILL
    version: str = "0.0.0"
    install_path: str = ""                          # 安装路径
    status: InstallStatus = InstallStatus.INSTALLING
    installed_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    auto_update: bool = False
    config_override: dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketplaceStats:
    """市场统计"""
    total_packages: int = 0
    total_downloads: int = 0
    total_installs: int = 0
    published_packages: int = 0
    deprecrated_packages: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_category: dict[str, int] = field(default_factory=dict)
    top_downloaded: list[dict[str, Any]] = field(default_factory=list)
    top_rated: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReviewRecord:
    """市场审核记录"""
    review_id: str = field(default_factory=lambda: str(uuid4()))
    package_id: str = ""
    reviewer_id: str = ""
    status: ReviewStatus = ReviewStatus.PENDING
    comments: str = ""
    issues: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    resolved_at: datetime | None = None
