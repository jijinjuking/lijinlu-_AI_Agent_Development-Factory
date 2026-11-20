"""
Context Builder — 上下文拼接器
检索 → 重排 → Token Budget 控制 → 拼接
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.runtime.context_engine.chunking import TextSplitter, Chunk
from app.runtime.context_engine.retrieval import VectorStore, VectorDoc
from app.runtime.context_engine.retrieval.retriever import HybridRetriever
from app.runtime.context_engine.semantic_cache import SemanticCache
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


@dataclass
class ContextResult:
    """上下文构建结果"""
    context: str
    sources: list[dict]           # 引用来源
    token_count: int = 0
    cache_hit: bool = False
    retrieval_count: int = 0
    rerank_count: int = 0         # 重排后的文档数
    metadata: dict = field(default_factory=dict)


class ContextBuilder:
    """
    上下文构建器。
    主流程：Cache → Retrieve → Rerank → Budget → Assemble → Cache
    """

    def __init__(
        self,
        retriever: HybridRetriever,
        cache: SemanticCache | None = None,
        text_splitter: TextSplitter | None = None,
        reranker=None,                        # CrossEncoderReranker | None
        max_context_tokens: int = 4000,
        max_sources: int = 10,
    ):
        self.retriever = retriever
        self.cache = cache or SemanticCache()
        self.text_splitter = text_splitter or TextSplitter()
        self.reranker = reranker              # 可选重排器
        self.max_context_tokens = max_context_tokens
        self.max_sources = max_sources

    async def build_context(
        self,
        query: str,
        project_id: str = "",
        token_budget: int | None = None,
        use_cache: bool = True,
        use_semantic_cache: bool = False,     # 是否启用语义缓存
        use_rerank: bool = True,              # 是否启用重排
        filters: dict | None = None,
    ) -> ContextResult:
        """
        构建上下文主入口。
        1. 查缓存（精确 + 语义）
        2. 混合检索
        3. 重排序（Reranker）
        4. Token Budget 控制
        5. 拼接
        6. 写缓存
        """
        budget = token_budget or self.max_context_tokens

        # 1. 语义缓存（双层：精确 SHA256 + 语义 Embedding 余弦相似度）
        if use_cache:
            if use_semantic_cache and self.cache.has_semantic:
                cached, sim_score = await self.cache.get_semantic(query, project_id)
                if cached is not None:
                    return ContextResult(
                        context=cached,
                        sources=[],
                        token_count=self.text_splitter.count_tokens(cached),
                        cache_hit=True,
                        metadata={"semantic_similarity": sim_score},
                    )
            else:
                cached = await self.cache.get(query, project_id)
                if cached is not None:
                    return ContextResult(
                        context=cached,
                        sources=[],
                        token_count=self.text_splitter.count_tokens(cached),
                        cache_hit=True,
                    )

        # 2. 混合检索（返回 2x 候选用于重排）
        retrieval_top_k = self.max_sources * 2
        docs = await self.retriever.search(
            query, top_k=retrieval_top_k, filters=filters,
        )

        if not docs:
            return ContextResult(context="", sources=[], token_count=0)

        retrieval_count = len(docs)

        # 3. 重排序（CrossEncoder / LLM Reranker）
        if use_rerank and self.reranker and len(docs) > 1:
            try:
                docs = await self.reranker.rerank(query, docs, top_k=self.max_sources)
                logger.debug("ContextBuilder: reranked %d → %d docs", retrieval_count, len(docs))
            except Exception as e:
                logger.warning("ContextBuilder: rerank failed, using original order: %s", e)
                docs = docs[:self.max_sources]

        rerank_count = len(docs)

        # 4. 相关性过滤（score < 0.1 过滤）
        relevant_docs = [d for d in docs if d.score >= 0.1]

        # 5. Token Budget 控制
        final_docs, used_tokens = self._apply_token_budget(relevant_docs, budget)

        # 6. 拼接上下文
        parts = []
        for i, doc in enumerate(final_docs, start=1):
            header = f"[Source {i}]"
            if doc.metadata.get("title"):
                header += f" {doc.metadata['title']}"
            if doc.metadata.get("chunk_index") is not None:
                header += f" (chunk {doc.metadata['chunk_index'] + 1}/{doc.metadata.get('total_chunks', '?')})"
            parts.append(f"{header}\n{doc.text}")

        context = "\n\n---\n\n".join(parts)

        # 7. 写缓存
        await self.cache.set(query, context, project_id)

        # 8. 构建来源引用
        sources = [d.to_dict() for d in final_docs]

        return ContextResult(
            context=context,
            sources=sources,
            token_count=used_tokens,
            cache_hit=False,
            retrieval_count=retrieval_count,
            rerank_count=rerank_count,
        )

    def _apply_token_budget(
        self, docs: list[VectorDoc], budget: int
    ) -> tuple[list[VectorDoc], int]:
        """
        Token Budget 控制。
        按相关性从高到低填充，直到预算耗尽。
        最后一个文档如果放不下，截断到剩余预算。
        """
        result: list[VectorDoc] = []
        used = 0

        for doc in docs:
            doc_tokens = self.text_splitter.count_tokens(doc.text)
            # 保留一些余量给分隔符
            overhead = 50 if result else 0

            if used + doc_tokens + overhead <= budget:
                result.append(doc)
                used += doc_tokens + overhead
            elif used < budget * 0.3:
                # 如果填充还很少，继续加
                result.append(doc)
                used += doc_tokens + overhead
            else:
                # 尝试截断最后一个文档
                remaining = budget - used - overhead
                if remaining > 100:
                    truncated = doc.text[:remaining * 4]  # 粗略截断
                    truncated_doc = VectorDoc(
                        id=doc.id,
                        vector=doc.vector,
                        text=truncated + "\n...",
                        metadata=doc.metadata,
                        score=doc.score,
                    )
                    result.append(truncated_doc)
                    used = budget
                break

        return result, min(used, budget)

    async def index_document(
        self, text: str, metadata: dict | None = None,
    ) -> list[str]:
        """索引文档：分块 → 向量化 → 存入 VectorStore"""
        chunks = self.text_splitter.split_text(text, metadata)
        if not chunks:
            return []

        texts = [c.text for c in chunks]
        metas = [c.metadata for c in chunks]
        ids = []

        # 批量向量化（使用 retriever 绑定的 embedding_service，确保维度一致）
        vectors = await self.retriever.embedding_service.embed(texts)

        # 存入向量存储
        ids = await self.retriever.vector_store.add(texts, vectors, metas)

        logger.info("ContextBuilder: indexed %d chunks from document", len(chunks))
        return ids

    async def index_memories(
        self, memories: list[dict], content_key: str = "content",
    ) -> list[str]:
        """批量索引记忆条目"""
        all_ids = []
        for mem in memories:
            text = mem.get(content_key, "")
            meta = {k: v for k, v in mem.items() if k != content_key}
            ids = await self.index_document(text, meta)
            all_ids.extend(ids)
        return all_ids
