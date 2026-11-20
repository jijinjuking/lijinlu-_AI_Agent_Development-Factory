"""
Semantic Cache — 语义缓存
双层缓存：精确匹配（SHA256）+ 语义匹配（Embedding 余弦相似度）
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    value: str
    query_embedding: list[float] | None = None
    project_id: str = ""
    created_at: float = field(default_factory=time.time)
    ttl_sec: int = 3600
    hit_count: int = 0

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_sec


class SemanticCache:
    """
    语义缓存。
    双层匹配策略：
    1. 精确匹配：SHA256(query, project_id) — O(1)，无假阳性
    2. 语义匹配：Embedding 余弦相似度 — O(n)，阈值可配

    Phase 1: 内存实现
    Phase 2: 可替换为 Redis
    """

    def __init__(
        self,
        max_entries: int = 1000,
        default_ttl_sec: int = 3600,
        embedding_service=None,        # 可选：用于语义匹配
        semantic_threshold: float = 0.92,  # 余弦相似度阈值
    ):
        self.max_entries = max_entries
        self.default_ttl = default_ttl_sec
        self._embed_service = embedding_service
        self.semantic_threshold = semantic_threshold
        self._store: dict[str, CacheEntry] = {}

    @property
    def has_semantic(self) -> bool:
        """是否支持语义匹配"""
        return self._embed_service is not None

    # ---- Key Generation ----

    @staticmethod
    def hash_key(query: str, project_id: str = "", extra: str = "") -> str:
        """生成精确缓存 key（SHA256 截断）"""
        raw = f"{project_id}:{query}:{extra}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # ---- Exact Match (SHA256) ----

    async def get(self, query: str, project_id: str = "", extra: str = "") -> str | None:
        """精确匹配获取缓存值，未命中返回 None"""
        key = self.hash_key(query, project_id, extra)
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expired:
            del self._store[key]
            return None
        entry.hit_count += 1
        logger.debug("SemanticCache: EXACT HIT key=%s (hits=%d)", key[:12], entry.hit_count)
        return entry.value

    # ---- Semantic Match (Embedding Cosine Similarity) ----

    async def get_semantic(self, query: str, project_id: str = "") -> tuple[str | None, float]:
        """
        语义匹配获取缓存值。
        返回 (value, similarity_score)，未命中返回 (None, 0.0)。
        如果未配置 embedding_service，退回精确匹配。
        """
        if not self._embed_service:
            val = await self.get(query, project_id)
            return (val, 1.0 if val else 0.0)

        # 先尝试精确匹配
        exact = await self.get(query, project_id)
        if exact is not None:
            return (exact, 1.0)

        # 语义匹配
        try:
            query_vec = await self._embed_service.embed_text(query)
        except Exception as e:
            logger.warning("SemanticCache: embed failed for query: %s", e)
            return (None, 0.0)

        best_entry: CacheEntry | None = None
        best_score = 0.0

        for entry in self._store.values():
            if entry.expired:
                continue
            if project_id and entry.project_id and entry.project_id != project_id:
                continue
            if entry.query_embedding is None:
                continue

            score = self._cosine_similarity(query_vec, entry.query_embedding)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_entry and best_score >= self.semantic_threshold:
            best_entry.hit_count += 1
            logger.debug(
                "SemanticCache: SEMANTIC HIT key=%s score=%.4f",
                best_entry.key[:12], best_score,
            )
            return (best_entry.value, best_score)

        return (None, best_score)

    # ---- Set ----

    async def set(
        self, query: str, value: str,
        project_id: str = "", extra: str = "",
        ttl_sec: int | None = None,
    ) -> str:
        """设置缓存值，返回 key"""
        key = self.hash_key(query, project_id, extra)

        # 淘汰策略：超过上限时删除最旧的
        if len(self._store) >= self.max_entries:
            oldest = min(self._store.values(), key=lambda e: e.created_at)
            del self._store[oldest.key]

        # 尝试嵌入查询
        query_embedding = None
        if self._embed_service:
            try:
                query_embedding = await self._embed_service.embed_text(query)
            except Exception as e:
                logger.debug("SemanticCache: embed failed on set: %s", e)

        self._store[key] = CacheEntry(
            key=key,
            value=value,
            query_embedding=query_embedding,
            project_id=project_id,
            ttl_sec=ttl_sec or self.default_ttl,
        )
        logger.debug("SemanticCache: SET key=%s, entries=%d", key[:12], len(self._store))
        return key

    # ---- Delete ----

    async def delete(self, key_or_query: str, project_id: str = "") -> bool:
        """删除缓存条目"""
        if key_or_query in self._store:
            del self._store[key_or_query]
            return True
        key = self.hash_key(key_or_query, project_id)
        if key in self._store:
            del self._store[key]
            return True
        return False

    async def clear(self, project_id: str = ""):
        """清空缓存"""
        if project_id:
            to_delete = [k for k, v in self._store.items() if v.project_id == project_id]
            for k in to_delete:
                del self._store[k]
        else:
            self._store.clear()

    # ---- Stats ----

    @property
    def stats(self) -> dict:
        """缓存统计"""
        total = len(self._store)
        hits = sum(e.hit_count for e in self._store.values())
        semantic_count = sum(1 for e in self._store.values() if e.query_embedding is not None)
        return {
            "total_entries": total,
            "max_entries": self.max_entries,
            "total_hits": hits,
            "default_ttl_sec": self.default_ttl,
            "has_semantic": self.has_semantic,
            "semantic_entries": semantic_count,
            "semantic_threshold": self.semantic_threshold,
        }

    # ---- Internal ----

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """余弦相似度"""
        if len(a) != len(b) or not a:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
