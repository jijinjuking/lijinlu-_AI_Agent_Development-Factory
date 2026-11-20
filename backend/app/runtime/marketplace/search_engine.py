"""
W29-30: AI Marketplace — 搜索引擎

基于 TF-IDF 的轻量级搜索，支持关键词匹配、模糊匹配、自动补全和排序。
"""

from __future__ import annotations

import math
import re
from collections import Counter

from app.runtime.marketplace.models import (
    MarketplacePackage,
    PackageStatus,
    PackageType,
    SearchQuery,
    SearchResult,
)


class SearchEngine:
    """能力包搜索引擎

    基于词频-逆文档频率（TF-IDF）实现轻量级全文搜索。
    - index() / deindex() 管理索引
    - search() 执行搜索
    - suggest() 提供搜索建议
    - 支持中文（单字分词）和英文（空格分词）
    """

    _CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
    _TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")

    def __init__(self):
        self._documents: dict[str, dict] = {}   # package_id -> search_doc
        self._inverted_index: dict[str, set[str]] = {}  # token -> {package_id}
        self._field_weights: dict[str, float] = {
            "name": 5.0,
            "display_name": 4.0,
            "tags": 3.5,
            "category": 2.0,
            "author": 1.5,
            "description": 2.0,
            "long_description": 1.0,
        }

    # ── 索引管理 ────────────────────────────────────────────────────────────

    async def index(self, package: MarketplacePackage):
        """索引一个能力包"""
        doc = package.to_search_doc()
        self._documents[package.package_id] = doc

        tokens = self._tokenize_doc(doc)
        for token in tokens:
            if token not in self._inverted_index:
                self._inverted_index[token] = set()
            self._inverted_index[token].add(package.package_id)

    async def deindex(self, package_id: str):
        """从索引中移除"""
        doc = self._documents.pop(package_id, None)
        if doc is None:
            return
        tokens = self._tokenize_doc(doc)
        for token in tokens:
            if token in self._inverted_index:
                self._inverted_index[token].discard(package_id)
                if not self._inverted_index[token]:
                    del self._inverted_index[token]

    async def reindex_all(self, packages: list[MarketplacePackage]):
        """重建全部索引"""
        self._documents.clear()
        self._inverted_index.clear()
        for pkg in packages:
            await self.index(pkg)

    # ── 搜索 ────────────────────────────────────────────────────────────────

    async def search(
        self,
        query: SearchQuery,
        packages: dict[str, MarketplacePackage],
    ) -> list[SearchResult]:
        """执行搜索

        流程：关键词分词 → TF-IDF 计算 → 筛选/排序 → 分页
        """
        if not query.keywords.strip():
            return self._search_by_filters(packages, query)

        # 分词
        query_tokens = self._tokenize(query.keywords)

        # TF-IDF 计算
        scores: dict[str, float] = self._compute_tfidf(query_tokens)

        # 转换为 SearchResult
        results: list[SearchResult] = []
        for pkg_id, score in scores.items():
            pkg = packages.get(pkg_id)
            if pkg is None:
                continue
            if not self._match_filters(pkg, query):
                continue
            results.append(self._to_result(pkg, score))

        # 排序
        results = self._sort_results(results, query)
        return results[query.offset:query.offset + query.page_size]

    async def suggest(
        self, prefix: str, limit: int = 10
    ) -> list[str]:
        """搜索建议 / 自动补全"""
        prefix_lower = prefix.lower()
        suggestions: set[str] = set()

        for pkg_id, doc in self._documents.items():
            name = doc.get("name", "")
            display = doc.get("display_name", "")
            if prefix_lower in name.lower() or prefix_lower in display.lower():
                suggestions.add(display or name)
            if len(suggestions) >= limit:
                break

        return list(suggestions)[:limit]

    def get_index_count(self) -> int:
        return len(self._documents)

    # ── 内部算法 ────────────────────────────────────────────────────────────

    def _tokenize(self, text: str) -> list[str]:
        """混合中英文分词"""
        tokens: list[str] = []

        # 英文字母+数字序列
        for match in self._TOKEN_RE.finditer(text):
            tokens.append(match.group().lower())

        # 中文字符逐个提取（可扩展为 jieba 分词）
        for ch in text:
            if self._CHINESE_CHAR_RE.match(ch):
                tokens.append(ch)

        return tokens

    def _tokenize_doc(self, doc: dict) -> list[str]:
        """对文档多字段分词，带字段权重"""
        all_tokens: list[str] = []
        for field, weight in self._field_weights.items():
            text = doc.get(field, "")
            if isinstance(text, list):
                text = " ".join(str(t) for t in text)
            elif not isinstance(text, str):
                text = str(text)
            tokens = self._tokenize(text)
            # 字段权重通过重复 token 实现
            repeat = max(1, int(weight))
            all_tokens.extend(tokens * repeat)
        return all_tokens

    def _compute_tfidf(self, query_tokens: list[str]) -> dict[str, float]:
        """计算 TF-IDF 分数"""
        if not self._documents:
            return {}

        doc_count = len(self._documents)
        scores: dict[str, float] = {}

        for token in query_tokens:
            matching_docs = self._inverted_index.get(token, set())
            if not matching_docs:
                continue

            # IDF
            idf = math.log((doc_count + 1) / (len(matching_docs) + 1)) + 1.0

            for pkg_id in matching_docs:
                if pkg_id not in self._documents:
                    continue
                doc = self._documents[pkg_id]
                # TF: 文档中 token 出现次数
                doc_text = " ".join(
                    str(doc.get(f, "")) if not isinstance(doc.get(f, ""), list)
                    else " ".join(str(t) for t in doc.get(f, ""))
                    for f in self._field_weights
                )
                doc_tokens = self._tokenize(doc_text)
                tf = doc_tokens.count(token) / max(len(doc_tokens), 1)
                scores[pkg_id] = scores.get(pkg_id, 0.0) + tf * idf

        return scores

    def _match_filters(self, pkg: MarketplacePackage, query: SearchQuery) -> bool:
        """检查包是否符合筛选条件"""
        if query.package_type is not None and pkg.package_type != query.package_type:
            return False
        if query.category is not None and pkg.category != query.category:
            return False
        if query.author is not None and pkg.author != query.author:
            return False
        if query.tags:
            pkg_tags = set(pkg.tags)
            if not all(t in pkg_tags for t in query.tags):
                return False
        if query.min_rating > 0 and pkg.average_rating < query.min_rating:
            return False
        if query.status is not None and pkg.status != query.status:
            return False
        # 默认只返回 published
        if query.status is None:
            if not pkg.status.is_available:
                return False
        return True

    def _search_by_filters(
        self, packages: dict[str, MarketplacePackage], query: SearchQuery,
    ) -> list[SearchResult]:
        """无关键词时的纯筛选搜索"""
        results: list[SearchResult] = []
        for pkg in packages.values():
            if self._match_filters(pkg, query):
                results.append(self._to_result(pkg, 0.0))

        results = self._sort_results(results, query)
        return results[query.offset:query.offset + query.page_size]

    def _to_result(self, pkg: MarketplacePackage, score: float) -> SearchResult:
        return SearchResult(
            package_id=pkg.package_id,
            name=pkg.name,
            display_name=pkg.display_name,
            package_type=pkg.package_type,
            description=pkg.description,
            author=pkg.author,
            version=pkg.version,
            download_count=pkg.download_count,
            average_rating=pkg.average_rating,
            tags=pkg.tags,
            category=pkg.category,
            relevance_score=round(score, 4),
        )

    def _sort_results(
        self, results: list[SearchResult], query: SearchQuery,
    ) -> list[SearchResult]:
        """按指定方式排序"""
        reverse = query.sort_order == "desc"
        if query.sort_by == "downloads":
            results.sort(key=lambda r: r.download_count, reverse=reverse)
        elif query.sort_by == "rating":
            results.sort(key=lambda r: r.average_rating, reverse=reverse)
        elif query.sort_by == "updated":
            results.sort(key=lambda r: r.relevance_score, reverse=reverse)  # fallback
        else:  # relevance
            results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results
