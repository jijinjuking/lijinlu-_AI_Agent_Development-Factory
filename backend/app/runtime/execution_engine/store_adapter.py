"""
Store Adapter — 将项目持久化层适配为 LangGraph BaseStore

Phase 3.5: langgraph.store 桥接
- LangGraph BaseStore 支持跨线程持久记忆（区别于 Checkpoint 的短期状态）
- 使用 SQLite 做持久化后端（项目已有 SQLite 配置）
- 可选接入 ContextEngine 做语义搜索

设计：
- namespace = 层次化路径，如 ("users", "profiles")
- key = 唯一标识
- value = dict（JSON 序列化）
- TTL 支持（基于 created_at/updated_at 过期）
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, NamedTuple, Optional, Sequence

from langchain_core.embeddings import Embeddings
from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    Op,
    PutOp,
    SearchItem,
    SearchOp,
)
from langgraph.store.base.embed import AEmbeddingsFunc, EmbeddingsFunc, ensure_embeddings

logger = logging.getLogger("ai_runtime_os.store_adapter")


# ── 内存实现（开发/测试用）───────────────────────────────────────


class StoreAdapter(BaseStore):
    """
    LangGraph BaseStore 的内存实现。

    用于开发和测试。生产环境应使用 SQLiteStore。
    支持 TTL 过期、语义搜索（如果配置了 embedding）。

    用法：
        store = InMemoryStore()
        await store.aput(("users",), "user1", {"name": "Alice"})
        item = await store.aget(("users",), "user1")
    """

    supports_ttl: bool = True

    def __init__(
        self,
        *,
        index: dict[str, Any] | None = None,
    ):
        """
        Args:
            index: 可选的索引配置（嵌入维度、嵌入函数、索引字段）
                 格式: {"dims": 1536, "embed": embedding_func, "fields": ["field1", ...]}
        """
        super().__init__()
        self._data: dict[tuple[str, ...], dict[str, dict]] = {}  # namespace -> {key -> item_dict}
        self._ttl_config = index.get("ttl_config") if isinstance(index, dict) else None
        # TODO: 如果配置了 index，初始化嵌入函数

    # ── 批量操作（核心）───────────────────────────────────────────────

    def batch(self, ops: Iterable[Op]) -> list[Any]:
        """同步 batch：在独立线程中运行 abatch（避免与调用方事件循环冲突）"""
        import asyncio
        import concurrent.futures

        def _run():
            return asyncio.run(self.abatch(ops))

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 无运行中的事件循环 → 直接 asyncio.run
            return _run()

        # 有运行中的事件循环 → 在独立线程中执行
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            return future.result()

    async def abatch(self, ops: Iterable[Op]) -> list[Any]:
        results = []
        for op in ops:
            if isinstance(op, GetOp):
                results.append(await self.aget(op.namespace, op.key))
            elif isinstance(op, SearchOp):
                results.append(await self.asearch(
                    op.namespace_prefix,
                    query=op.query,
                    filter=op.filter,
                    limit=op.limit,
                    offset=op.offset,
                ))
            elif isinstance(op, PutOp):
                if op.value is None:
                    # value=None 表示删除
                    await self.adelete(op.namespace, op.key)
                    results.append(None)
                else:
                    await self.aput(
                        op.namespace, op.key, op.value,
                        index=op.index, ttl=op.ttl,
                    )
                    results.append(None)
            elif isinstance(op, ListNamespacesOp):
                results.append(await self.alist_namespaces(
                    prefix=op.prefix,
                    suffix=op.suffix,
                    max_depth=op.max_depth,
                    limit=op.limit,
                    offset=op.offset,
                ))
            else:
                logger.warning("Unknown op type: %s", type(op))
                results.append(None)
        return results

    # ── Get ───────────────────────────────────────────────────────────

    async def aget(
        self,
        namespace: tuple[str, ...],
        key: str,
        *,
        refresh_ttl: bool | None = None,
    ) -> Item | None:
        await self._expire(namespace)
        ns_data = self._data.get(namespace)
        if ns_data is None:
            return None
        item_dict = ns_data.get(key)
        if item_dict is None:
            return None
        return self._dict_to_item(namespace, key, item_dict)

    # ── Search ─────────────────────────────────────────────────────

    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        refresh_ttl: bool | None = None,
    ) -> list[SearchItem]:
        import fnmatch
        import re

        results: list[SearchItem] = []

        for ns, ns_data in self._data.items():
            # 匹配 namespace_prefix
            if not self._match_prefix(ns, namespace_prefix):
                continue
            await self._expire(ns)
            for key, item_dict in ns_data.items():
                value = item_dict.get("value", {})
                # 结构化过滤
                if filter and not self._match_filter(value, filter):
                    continue
                # TODO: 语义搜索（如果配置了 query 和 embedding）
                score = 1.0  # TODO: 语义相似度
                results.append(SearchItem(
                    namespace=ns,
                    key=key,
                    value=value,
                    created_at=datetime.fromisoformat(item_dict["created_at"]),
                    updated_at=datetime.fromisoformat(item_dict["updated_at"]),
                    score=score,
                ))

        # 排序、分页
        results.sort(key=lambda x: x.score if x.score is not None else 0.0, reverse=True)
        return results[offset:offset + limit]

    # ── Put ───────────────────────────────────────────────────────────

    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        *,
        index: bool | list[str] | None = None,
        ttl: float | None = None,
    ) -> None:
        if namespace not in self._data:
            self._data[namespace] = {}
        now = datetime.now(timezone.utc).isoformat()
        existing = self._data[namespace].get(key)
        created_at = existing["created_at"] if existing else now
        self._data[namespace][key] = {
            "value": value,
            "created_at": created_at,
            "updated_at": now,
            "ttl": ttl,
        }
        logger.debug("Stored: ns=%s key=%s", namespace, key)

    # ── Delete ─────────────────────────────────────────────────────

    async def adelete(
        self,
        namespace: tuple[str, ...],
        key: str,
    ) -> None:
        if namespace in self._data and key in self._data[namespace]:
            del self._data[namespace][key]
            logger.debug("Deleted: ns=%s key=%s", namespace, key)

    # ── List Namespaces ─────────────────────────────────────────

    async def alist_namespaces(
        self,
        *,
        prefix: tuple[str | Literal["*"], ...] | None = None,
        suffix: tuple[str | Literal["*"], ...] | None = None,
        max_depth: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[str, ...]]:
        import fnmatch

        namespaces = list(self._data.keys())
        # 前缀匹配
        if prefix:
            filtered = []
            for ns in namespaces:
                if self._match_namespace_path(ns, prefix):
                    filtered.append(ns)
            namespaces = filtered
        # 后缀匹配
        if suffix:
            filtered = []
            for ns in namespaces:
                if self._match_namespace_path(ns[::-1], suffix[::-1]):
                    filtered.append(ns)
            namespaces = filtered
        # 深度限制
        if max_depth is not None:
            namespaces = [ns for ns in namespaces if len(ns) <= max_depth]
        # 分页
        return sorted(set(namespaces))[offset:offset + limit]

    # ── List Items ──────────────────────────────────────────────

    async def alist(
        self,
        namespace: tuple[str, ...],
        *,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        refresh_ttl: bool | None = None,
    ) -> list[Item]:
        await self._expire(namespace)
        ns_data = self._data.get(namespace)
        if ns_data is None:
            return []
        items = []
        for key, item_dict in ns_data.items():
            value = item_dict.get("value", {})
            if filter and not self._match_filter(value, filter):
                continue
            items.append(self._dict_to_item(namespace, key, item_dict))
        return items[offset:offset + limit]

    # ── 内部工具方法 ──────────────────────────────────────────────

    @staticmethod
    def _dict_to_item(ns: tuple[str, ...], key: str, d: dict) -> Item:
        return Item(
            value=d["value"],
            key=key,
            namespace=ns,
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
        )

    @staticmethod
    def _match_prefix(ns: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
        if len(prefix) > len(ns):
            return False
        for i, p in enumerate(prefix):
            if p == "*":
                continue
            if ns[i] != p:
                return False
        return True

    @staticmethod
    def _match_namespace_path(
        ns: tuple[str, ...], pattern: tuple[str | Literal["*"], ...],
    ) -> bool:
        if len(pattern) > len(ns):
            return False
        for i, p in enumerate(pattern):
            if p == "*":
                continue
            if ns[i] != p:
                return False
        return True

    @staticmethod
    def _match_filter(value: dict, filter_spec: dict) -> bool:
        """简单的结构化过滤（支持 $eq/$ne/$gt/$gte/$lt/$lte）"""
        for k, v in filter_spec.items():
            actual = value.get(k)
            if isinstance(v, dict):
                for op, target in v.items():
                    if op == "$eq" and actual != target:
                        return False
                    if op == "$ne" and actual == target:
                        return False
                    if op == "$gt" and (actual is None or actual <= target):
                        return False
                    if op == "$gte" and (actual is None or actual < target):
                        return False
                    if op == "$lt" and (actual is None or actual >= target):
                        return False
                    if op == "$lte" and (actual is None or actual > target):
                        return False
            else:
                if actual != v:
                    return False
        return True

    async def _expire(self, namespace: tuple[str, ...]) -> None:
        """过期删除（如果配置了 TTL）"""
        if namespace not in self._data:
            return
        now = datetime.now(timezone.utc)
        to_delete = []
        for key, item_dict in self._data[namespace].items():
            ttl = item_dict.get("ttl")
            if ttl is not None:
                updated = datetime.fromisoformat(item_dict["updated_at"])
                if (now - updated).total_seconds() > ttl * 60:
                    to_delete.append(key)
        for key in to_delete:
            del self._data[namespace][key]
