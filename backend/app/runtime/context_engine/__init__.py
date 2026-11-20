"""
Context Engine — 上下文引擎主入口
组合 Embedding + Chunking + VectorStore + Retriever + Builder + Cache
"""
from __future__ import annotations

import logging
from typing import Optional

from app.services.embedding_service import EmbeddingService, embedding_service
from app.runtime.context_engine.chunking import TextSplitter, CodeSplitter, CodeChunk
from app.runtime.context_engine.reranking import CrossEncoderReranker
from app.runtime.context_engine.compression import LLMCompressor, CompressionResult
from app.runtime.context_engine.retrieval import VectorStore
from app.runtime.context_engine.retrieval.retriever import HybridRetriever
from app.runtime.context_engine.context_builder import ContextBuilder, ContextResult
from app.runtime.context_engine.semantic_cache import SemanticCache

logger = logging.getLogger(__name__)


class ContextEngine:
    """
    上下文引擎。
    统一入口：索引 → 检索 → 构建 → 注入。

    用法:
        engine = ContextEngine()
        await engine.index("some document text", {"type": "memory"})
        result = await engine.build("what is the architecture?", project_id="proj-1")
        print(result.context)
    """

    def __init__(
        self,
        embed_service: EmbeddingService | None = None,
        vector_store: VectorStore | None = None,
        text_splitter: TextSplitter | None = None,
        cache: SemanticCache | None = None,
        vector_dim: int = 1536,
        max_context_tokens: int = 4000,
    ):
        # Embedding
        self.embed_service = embed_service or embedding_service

        # Chunking
        self.text_splitter = text_splitter or TextSplitter()

        # Vector Store
        self.vector_store = vector_store or VectorStore(dim=vector_dim)

        # Cache
        self.cache = cache or SemanticCache()

        # Retriever
        self.retriever = HybridRetriever(
            vector_store=self.vector_store,
            embedding_service=self.embed_service,
        )

        # Builder
        self.builder = ContextBuilder(
            retriever=self.retriever,
            cache=self.cache,
            text_splitter=self.text_splitter,
            max_context_tokens=max_context_tokens,
        )

        self.max_context_tokens = max_context_tokens

    # ---- Public API ----

    async def index(
        self, text: str, metadata: dict | None = None,
    ) -> list[str]:
        """索引文本（分块 + 向量化 + 存储）"""
        return await self.builder.index_document(text, metadata)

    async def index_batch(
        self, documents: list[dict], content_key: str = "content",
    ) -> list[str]:
        """批量索引文档"""
        all_ids = []
        for doc in documents:
            text = doc.get(content_key, "")
            meta = {k: v for k, v in doc.items() if k != content_key}
            ids = await self.index(text, meta)
            all_ids.extend(ids)
        return all_ids

    async def search(
        self, query: str, top_k: int = 5, filters: dict | None = None,
    ) -> list[dict]:
        """语义搜索（返回原始结果，不拼接上下文）"""
        docs = await self.retriever.search(query, top_k=top_k, filters=filters)
        return [d.to_dict() for d in docs]

    async def build(
        self,
        query: str,
        project_id: str = "",
        token_budget: int | None = None,
        use_cache: bool = True,
        filters: dict | None = None,
    ) -> ContextResult:
        """构建上下文（检索 + 拼接）"""
        return await self.builder.build_context(
            query=query,
            project_id=project_id,
            token_budget=token_budget or self.max_context_tokens,
            use_cache=use_cache,
            filters=filters,
        )

    async def inject(
        self, query: str, project_id: str = "",
        token_budget: int | None = None,
    ) -> str:
        """
        注入上下文到 system prompt。
        返回格式化的上下文文本块，可直接拼接到 prompt 中。
        """
        result = await self.build(query, project_id, token_budget)
        if not result.context:
            return ""

        return f"""## Relevant Context

The following information may be relevant to the current task:

{result.context}

---
"""

    # ---- Management ----

    @property
    def stats(self) -> dict:
        """引擎统计"""
        return {
            "vector_store_count": self.vector_store.count,
            "cache": self.cache.stats,
            "embedding_dim": self.embed_service.dim,
            "max_context_tokens": self.max_context_tokens,
        }

    async def clear_cache(self, project_id: str = ""):
        """清空缓存"""
        await self.cache.clear(project_id)

    async def clear_index(self):
        """清空向量索引"""
        await self.vector_store.clear()
        await self.cache.clear()

    def save_index(self, path: str):
        """保存索引到磁盘"""
        self.vector_store.save(path)

    def load_index(self, path: str):
        """从磁盘加载索引"""
        self.vector_store._load(path)


# 全局单例
context_engine = ContextEngine()
