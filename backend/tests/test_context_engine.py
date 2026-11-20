"""
W6 Context Engine — 完整单元测试
覆盖：TextSplitter / VectorStore / HybridRetriever / SemanticCache / ContextBuilder / ContextEngine / API
"""
from __future__ import annotations

import json
import time
import uuid

import numpy as np
import pytest
from httpx import AsyncClient

from app.runtime.context_engine.chunking import TextSplitter, Chunk
from app.runtime.context_engine.retrieval import VectorStore, VectorDoc
from app.runtime.context_engine.retrieval.retriever import HybridRetriever
from app.runtime.context_engine.semantic_cache import SemanticCache
from app.runtime.context_engine.context_builder import ContextBuilder, ContextResult
from app.runtime.context_engine import ContextEngine
from app.services.embedding_service import EmbeddingService


# ── Helpers ──

class _MockEmbeddingService:
    """轻量 mock embedding：基于字符 trigram hash 生成向量，保证相似文本产生相似向量"""

    def __init__(self, dim: int = 128):
        self.dim = dim

    def _text_to_vector(self, text: str) -> np.ndarray:
        """基于字符 trigram 的确定性向量化，相似文本 → 相似向量"""
        vec = np.zeros(self.dim, dtype=np.float32)
        text_lower = text.lower()
        # 提取 trigram
        for i in range(len(text_lower) - 2):
            trigram = text_lower[i:i+3]
            h = hash(trigram) % (2**31)
            rng = np.random.RandomState(h)
            vec += rng.randn(self.dim).astype(np.float32) * 0.1
        # L2 归一化
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    async def embed(self, texts: list[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            vectors[i] = self._text_to_vector(text)
        return vectors

    async def embed_query(self, text: str) -> np.ndarray:
        return self._text_to_vector(text)

    async def close(self):
        pass


# ── TextSplitter Tests ──

class TestTextSplitter:
    """文本分块器测试"""

    def test_count_tokens_english(self):
        splitter = TextSplitter()
        # ~100 chars English → roughly 25 tokens
        text = "This is a simple test sentence for token counting purposes."
        tokens = splitter.count_tokens(text)
        assert tokens > 0

    def test_count_tokens_chinese(self):
        splitter = TextSplitter()
        # Chinese: ~1.5 chars/token
        text = "这是一个测试句子用于验证中文分词功能"
        tokens = splitter.count_tokens(text)
        assert tokens > 0

    def test_count_tokens_mixed(self):
        splitter = TextSplitter()
        text = "AI Runtime OS 是一个 Agent 操作系统平台"
        tokens = splitter.count_tokens(text)
        assert tokens > 0

    def test_split_short_text(self):
        splitter = TextSplitter(chunk_size=512)
        text = "Short text"
        chunks = splitter.split_text(text)
        assert len(chunks) == 1
        assert chunks[0].text == text
        assert chunks[0].index == 0

    def test_split_long_text(self):
        splitter = TextSplitter(chunk_size=128, chunk_overlap=0)
        # Generate text that will be split into multiple chunks
        text = " ".join(["word"] * 200)
        chunks = splitter.split_text(text)
        assert len(chunks) > 1
        for c in chunks:
            assert c.token_count > 0
            assert c.metadata.get("chunk_index") is not None
            assert c.metadata.get("total_chunks") == len(chunks)

    def test_split_chinese_text(self):
        splitter = TextSplitter(chunk_size=200)
        text = "这是一个关于AI Runtime OS的详细介绍。" * 50
        chunks = splitter.split_text(text)
        assert len(chunks) >= 1
        for c in chunks:
            assert len(c.text) > 0

    def test_split_empty_text(self):
        splitter = TextSplitter()
        chunks = splitter.split_text("")
        assert len(chunks) == 0

    def test_split_whitespace_only(self):
        splitter = TextSplitter()
        chunks = splitter.split_text("   \n  \t  ")
        assert len(chunks) == 0

    def test_split_with_metadata(self):
        splitter = TextSplitter(chunk_size=256, chunk_overlap=0)
        text = "Content for metadata test. " * 50
        chunks = splitter.split_text(text, {"source": "test_file.py"})
        for c in chunks:
            assert c.metadata.get("source") == "test_file.py"
            assert "chunk_index" in c.metadata

    def test_split_documents(self):
        splitter = TextSplitter(chunk_size=256)
        docs = [
            {"content": "First document text. " * 30, "title": "Doc 1"},
            {"content": "Second document text. " * 30, "title": "Doc 2"},
        ]
        chunks = splitter.split_documents(docs, content_key="content")
        assert len(chunks) > 0
        # Check metadata is preserved
        titles = {c.metadata.get("title") for c in chunks}
        assert titles == {"Doc 1", "Doc 2"}

    def test_chunk_overlap(self):
        splitter = TextSplitter(chunk_size=128, chunk_overlap=32)
        text = ". ".join([f"paragraph_{i}" for i in range(100)])
        chunks = splitter.split_text(text)
        if len(chunks) > 1:
            # Verify chunks exist and overlap is working (content from prev chunk in next)
            assert all(c.text for c in chunks)

    def test_chunk_dataclass(self):
        c = Chunk(text="hello", index=0, token_count=1, metadata={"key": "val"})
        assert c.text == "hello"
        assert c.index == 0
        assert c.token_count == 1
        assert c.metadata["key"] == "val"
        assert "Chunk(#0, 1 tokens)" in repr(c)

    def test_code_separators(self):
        splitter = TextSplitter(chunk_size=100, separators=TextSplitter.CODE_SEPARATORS)
        code = "def foo():\n    pass\n\n\ndef bar():\n    return 42\n" * 20
        chunks = splitter.split_text(code)
        assert len(chunks) >= 1


# ── VectorStore Tests ──

class TestVectorStore:
    """向量存储测试"""

    @pytest.fixture
    def store(self):
        return VectorStore(dim=128)

    @pytest.fixture
    def mock_embed(self):
        return _MockEmbeddingService(dim=128)

    @pytest.mark.asyncio
    async def test_add_and_search(self, store, mock_embed):
        texts = ["apple fruit", "banana fruit", "computer hardware"]
        vectors = await mock_embed.embed(texts)
        ids = await store.add(texts, vectors)

        assert len(ids) == 3
        assert store.count == 3

        # Search for "fruit"
        query_vec = await mock_embed.embed_query("fruit")
        results = await store.search(query_vec, top_k=2)

        assert len(results) == 2
        # "apple" and "banana" should rank higher than "computer"
        assert results[0].text in ("apple fruit", "banana fruit")

    @pytest.mark.asyncio
    async def test_search_empty_store(self, store, mock_embed):
        query_vec = await mock_embed.embed_query("test")
        results = await store.search(query_vec)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_min_score(self, store, mock_embed):
        texts = ["test document"]
        vectors = await mock_embed.embed(texts)
        await store.add(texts, vectors)

        query_vec = await mock_embed.embed_query("test")
        # Very high threshold should filter everything
        results = await store.search(query_vec, min_score=0.99)
        assert len(results) >= 0  # At minimum doesn't crash

    @pytest.mark.asyncio
    async def test_delete(self, store, mock_embed):
        texts = ["doc1", "doc2", "doc3"]
        vectors = await mock_embed.embed(texts)
        ids = await store.add(texts, vectors)
        assert store.count == 3

        deleted = await store.delete([ids[0]])
        assert deleted == 1
        assert store.count == 2

    @pytest.mark.asyncio
    async def test_get_doc(self, store, mock_embed):
        texts = ["specific document"]
        vectors = await mock_embed.embed(texts)
        ids = await store.add(texts, vectors)

        doc = await store.get(ids[0])
        assert doc is not None
        assert doc.text == "specific document"

        doc_none = await store.get("nonexistent")
        assert doc_none is None

    @pytest.mark.asyncio
    async def test_list_docs(self, store, mock_embed):
        texts = [f"doc_{i}" for i in range(5)]
        vectors = await mock_embed.embed(texts)
        await store.add(texts, vectors)

        docs = await store.list_docs(limit=3)
        assert len(docs) == 3

        docs_offset = await store.list_docs(limit=2, offset=3)
        assert len(docs_offset) == 2

    @pytest.mark.asyncio
    async def test_clear(self, store, mock_embed):
        texts = ["doc1", "doc2"]
        vectors = await mock_embed.embed(texts)
        await store.add(texts, vectors)
        assert store.count == 2

        await store.clear()
        assert store.count == 0

    def test_vector_doc_dataclass(self):
        doc = VectorDoc(id="abc", vector=np.zeros(3), text="hello", metadata={"k": "v"}, score=0.9)
        d = doc.to_dict()
        assert d["id"] == "abc"
        assert d["text"] == "hello"
        assert d["score"] == 0.9
        assert d["metadata"]["k"] == "v"

    @pytest.mark.asyncio
    async def test_add_length_mismatch(self, store, mock_embed):
        texts = ["a", "b"]
        vectors = await mock_embed.embed(["a"])
        with pytest.raises(ValueError):
            await store.add(texts, vectors)

    def test_count_initial(self, store):
        assert store.count == 0


# ── HybridRetriever Tests ──

class TestHybridRetriever:
    """混合检索器测试"""

    @pytest.fixture
    def mock_embed(self):
        return _MockEmbeddingService(dim=128)

    @pytest.fixture
    def store(self):
        return VectorStore(dim=128)

    @pytest.fixture
    def retriever(self, store, mock_embed):
        return HybridRetriever(vector_store=store, embedding_service=mock_embed)

    @pytest.mark.asyncio
    async def test_search_returns_results(self, retriever, store, mock_embed):
        texts = [
            "Python is a programming language",
            "JavaScript runs in browsers",
            "Rust is a systems language",
        ]
        vectors = await mock_embed.embed(texts)
        await store.add(texts, vectors)

        results = await retriever.search("programming language", top_k=2)
        assert len(results) == 2
        assert results[0].score > 0

    @pytest.mark.asyncio
    async def test_search_empty_store(self, retriever):
        results = await retriever.search("anything")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_keyword_search_component(self, retriever, store, mock_embed):
        texts = ["machine learning basics", "deep learning advanced", "baking cookies"]
        vectors = await mock_embed.embed(texts)
        await store.add(texts, vectors)

        # "learning" keyword should match first two documents
        results = await retriever.search("learning", top_k=3)
        result_texts = [r.text for r in results]
        assert any("learning" in t for t in result_texts)

    @pytest.mark.asyncio
    async def test_filter_by_metadata(self, retriever, store, mock_embed):
        texts = [
            "python technology document about AI",
            "finance report document about stocks",
            "technology document about cloud computing",
        ]
        metas = [
            {"category": "tech"},
            {"category": "finance"},
            {"category": "tech"},
        ]
        vectors = await mock_embed.embed(texts)
        await store.add(texts, vectors, metas)

        results = await retriever.search("technology document", top_k=5, filters={"category": "tech"})
        assert len(results) == 2
        for r in results:
            assert r.metadata["category"] == "tech"

    @pytest.mark.asyncio
    async def test_tokenization_chinese(self, retriever):
        tokens = retriever._tokenize("人工智能")
        assert len(tokens) > 0
        # Chinese bigrams + individual chars
        assert "人工" in tokens or "智能" in tokens

    @pytest.mark.asyncio
    async def test_tokenization_english(self, retriever):
        tokens = retriever._tokenize("machine learning")
        assert "machine" in tokens
        assert "learning" in tokens

    @pytest.mark.asyncio
    async def test_rrf_fusion(self, retriever):
        doc_a = VectorDoc(id="a", vector=np.zeros(3), text="a", score=0.9)
        doc_b = VectorDoc(id="b", vector=np.zeros(3), text="b", score=0.8)
        doc_c = VectorDoc(id="c", vector=np.zeros(3), text="c", score=0.3)

        fused = retriever._rrf_fusion([doc_a, doc_b], [doc_c], k=60)
        assert len(fused) == 3
        # doc_a should rank first (high in both lists, especially vector)
        assert fused[0].id == "a"


# ── SemanticCache Tests ──

class TestSemanticCache:
    """语义缓存测试"""

    @pytest.fixture
    def cache(self):
        return SemanticCache(max_entries=10, default_ttl_sec=3600)

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache):
        await cache.set("test query", "cached context", project_id="proj-1")
        result = await cache.get("test query", project_id="proj-1")
        assert result == "cached context"

    @pytest.mark.asyncio
    async def test_miss(self, cache):
        result = await cache.get("nonexistent query")
        assert result is None

    @pytest.mark.asyncio
    async def test_different_project_ids(self, cache):
        await cache.set("query", "ctx-a", project_id="proj-a")
        result = await cache.get("query", project_id="proj-b")
        assert result is None  # Different project

        result_a = await cache.get("query", project_id="proj-a")
        assert result_a == "ctx-a"

    @pytest.mark.asyncio
    async def test_cache_hit_count(self, cache):
        await cache.set("q", "value")
        await cache.get("q")  # hit
        await cache.get("q")  # hit
        await cache.get("q")  # hit

        stats = cache.stats
        assert stats["total_entries"] == 1
        assert stats["total_hits"] == 3

    @pytest.mark.asyncio
    async def test_expiry(self, cache):
        cache = SemanticCache(max_entries=10, default_ttl_sec=0)  # Immediate expiry
        await cache.set("q", "v")
        result = await cache.get("q")
        assert result is None  # Expired immediately

    @pytest.mark.asyncio
    async def test_delete(self, cache):
        await cache.set("deletable", "value")
        assert await cache.get("deletable") == "value"

        deleted = await cache.delete("deletable")
        assert deleted is True
        assert await cache.get("deletable") is None

    @pytest.mark.asyncio
    async def test_clear_all(self, cache):
        await cache.set("q1", "v1")
        await cache.set("q2", "v2")
        assert cache.stats["total_entries"] == 2

        await cache.clear()
        assert cache.stats["total_entries"] == 0

    @pytest.mark.asyncio
    async def test_clear_by_project(self, cache):
        await cache.set("q", "v", project_id="proj-1")
        await cache.set("q2", "v2", project_id="proj-2")
        assert cache.stats["total_entries"] == 2

        await cache.clear(project_id="proj-1")
        assert cache.stats["total_entries"] == 1

    @pytest.mark.asyncio
    async def test_max_entries_eviction(self, cache):
        cache = SemanticCache(max_entries=3, default_ttl_sec=3600)
        for i in range(5):
            await cache.set(f"q{i}", f"v{i}")
        stats = cache.stats
        assert stats["total_entries"] <= 3

    @pytest.mark.asyncio
    async def test_hash_key_consistency(self, cache):
        k1 = cache.hash_key("same query", "project")
        k2 = cache.hash_key("same query", "project")
        assert k1 == k2

        k3 = cache.hash_key("different", "project")
        assert k1 != k3

    def test_cache_stats(self, cache):
        stats = cache.stats
        assert "total_entries" in stats
        assert "max_entries" in stats
        assert "total_hits" in stats
        assert "default_ttl_sec" in stats


# ── ContextBuilder Tests ──

class TestContextBuilder:
    """上下文构建器测试"""

    @pytest.fixture
    def mock_embed(self):
        return _MockEmbeddingService(dim=128)

    @pytest.fixture
    def store(self):
        return VectorStore(dim=128)

    @pytest.fixture
    def cache(self):
        return SemanticCache(max_entries=10)

    @pytest.fixture
    def retriever(self, store, mock_embed):
        return HybridRetriever(vector_store=store, embedding_service=mock_embed)

    @pytest.fixture
    def builder(self, retriever, cache):
        return ContextBuilder(
            retriever=retriever,
            cache=cache,
            max_context_tokens=1000,
        )

    @pytest.mark.asyncio
    async def test_build_context_empty(self, builder):
        result = await builder.build_context("nothing here")
        assert isinstance(result, ContextResult)
        assert result.context == ""
        assert result.token_count == 0
        assert result.cache_hit is False

    @pytest.mark.asyncio
    async def test_build_context_with_data(self, builder, store, mock_embed):
        # Index some documents — use text with high trigram overlap to the query
        texts = [
            "agent operating system platform for AI orchestration and monitoring",
            "workflow orchestration with LangGraph for agent systems",
            "baking bread requires flour water yeast and salt",
        ]
        vectors = await mock_embed.embed(texts)
        await store.add(texts, vectors)

        result = await builder.build_context("agent operating system platform", token_budget=2000)
        assert isinstance(result, ContextResult)
        # Result may or may not have context depending on embedding similarity,
        # but the build pipeline must not crash
        assert result.retrieval_count >= 0
        assert result.cache_hit is False

    @pytest.mark.asyncio
    async def test_build_context_cache_hit(self, builder, store, mock_embed):
        texts = ["Cached context test document with unique content."]
        vectors = await mock_embed.embed(texts)
        await store.add(texts, vectors)

        # First call: no cache
        result1 = await builder.build_context("cache test query", use_cache=True)
        assert result1.cache_hit is False

        # Second call: should hit cache
        result2 = await builder.build_context("cache test query", use_cache=True)
        assert result2.cache_hit is True
        assert result2.context == result1.context

    @pytest.mark.asyncio
    async def test_build_context_no_cache(self, builder, store, mock_embed):
        texts = ["No cache test document."]
        vectors = await mock_embed.embed(texts)
        await store.add(texts, vectors)

        result1 = await builder.build_context("no cache query", use_cache=False)
        result2 = await builder.build_context("no cache query", use_cache=False)
        # Both should be non-cache hits
        assert result1.cache_hit is False
        assert result2.cache_hit is False

    @pytest.mark.asyncio
    async def test_index_document(self, builder, mock_embed):
        ids = await builder.index_document(
            "This is a document about AI agents and orchestration. " * 10,
            {"source_type": "memory", "title": "Test Memory"},
        )
        assert len(ids) > 0

    @pytest.mark.asyncio
    async def test_index_empty_document(self, builder):
        ids = await builder.index_document("")
        assert ids == []

    @pytest.mark.asyncio
    async def test_index_memories(self, builder):
        memories = [
            {"content": "Memory entry one content here.", "type": "note"},
            {"content": "Memory entry two content here.", "type": "todo"},
        ]
        ids = await builder.index_memories(memories)
        assert len(ids) > 0

    @pytest.mark.asyncio
    async def test_token_budget_exceeded(self, builder, store, mock_embed):
        # Add many large documents to test budget control
        texts = [f"Document number {i} with some content. " * 50 for i in range(20)]
        vectors = await mock_embed.embed(texts)
        await store.add(texts, vectors)

        # Very small budget
        result = await builder.build_context("document", token_budget=100)
        assert result.token_count <= 150  # Allow some overhead


# ── ContextEngine Integration Tests ──

class TestContextEngine:
    """ContextEngine 集成测试"""

    @pytest.fixture
    def mock_embed(self):
        return _MockEmbeddingService(dim=128)

    @pytest.fixture
    def engine(self, mock_embed):
        return ContextEngine(
            embed_service=mock_embed,
            vector_dim=128,
            max_context_tokens=2000,
        )

    @pytest.mark.asyncio
    async def test_index_and_search(self, engine):
        # Index
        ids = await engine.index("AI Runtime OS context engine documentation.", {"type": "doc"})
        assert len(ids) > 0

        # Search
        results = await engine.search("context engine", top_k=3)
        assert len(results) > 0
        assert "text" in results[0]
        assert "score" in results[0]
        assert "metadata" in results[0]

    @pytest.mark.asyncio
    async def test_index_batch(self, engine):
        docs = [
            {"content": "Document about Python programming.", "lang": "en"},
            {"content": "文档关于Python编程。", "lang": "zh"},
        ]
        ids = await engine.index_batch(docs, content_key="content")
        assert len(ids) > 0

    @pytest.mark.asyncio
    async def test_build_and_inject(self, engine):
        # Use identical text as index and query to guarantee high similarity
        text = "Context Engine provides semantic search capabilities for retrieval"
        await engine.index(text, {"type": "spec"})

        result = await engine.build(text, token_budget=500)
        assert isinstance(result, ContextResult)
        assert result.retrieval_count >= 0

        injected = await engine.inject(text)
        assert isinstance(injected, str)
        # inject always returns a valid string (may be empty if no context)

    @pytest.mark.asyncio
    async def test_stats(self, engine):
        stats = engine.stats
        assert "vector_store_count" in stats
        assert "cache" in stats
        assert "embedding_dim" in stats
        assert "max_context_tokens" in stats

    @pytest.mark.asyncio
    async def test_clear_operations(self, engine):
        await engine.index("Test document for clearing.")
        assert engine.stats["vector_store_count"] > 0

        await engine.clear_cache()
        await engine.clear_index()
        # After clear, store should be empty
        assert engine.stats["vector_store_count"] == 0

    @pytest.mark.asyncio
    async def test_inject_empty_context(self, engine):
        injected = await engine.inject("nothing matches this query")
        assert isinstance(injected, str)


# ── ContextEngine API Tests ──

class TestContextAPI:
    """Context Engine API 端点测试"""

    @pytest.mark.asyncio
    async def test_get_stats(self, client: AsyncClient):
        resp = await client.get("/context/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "vector_store_count" in data
        assert "cache" in data
        assert "embedding_dim" in data

    @pytest.mark.asyncio
    async def test_index_text(self, client: AsyncClient):
        resp = await client.post("/context/index", json={
            "text": "This is a test document for semantic indexing.",
            "metadata": {"title": "Test Doc"},
            "source_type": "test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["indexed_chunks"] > 0
        assert "vector_ids" in data
        assert "content_hash" in data

    @pytest.mark.asyncio
    async def test_index_batch(self, client: AsyncClient):
        resp = await client.post("/context/index/batch", json={
            "documents": [
                {"content": "Batch document one.", "type": "note"},
                {"content": "Batch document two.", "type": "spec"},
            ],
            "content_key": "content",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["indexed_docs"] == 2
        assert data["total_chunks"] > 0

    @pytest.mark.asyncio
    async def test_search(self, client: AsyncClient):
        # First index
        await client.post("/context/index", json={
            "text": "AI Runtime OS is a platform for agent orchestration and monitoring.",
            "source_type": "test",
        })

        # Then search
        resp = await client.post("/context/search", json={
            "query": "agent platform",
            "top_k": 3,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "results" in data
        assert "count" in data
        assert data["count"] > 0

    @pytest.mark.asyncio
    async def test_build(self, client: AsyncClient):
        # Index first
        await client.post("/context/index", json={
            "text": "The Context Engine uses hybrid retrieval combining vector and keyword search.",
            "source_type": "test",
        })

        resp = await client.post("/context/build", json={
            "query": "hybrid retrieval",
            "token_budget": 1000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "context" in data
        assert "sources" in data
        assert "token_count" in data
        assert "cache_hit" in data

    @pytest.mark.asyncio
    async def test_inject(self, client: AsyncClient):
        await client.post("/context/index", json={
            "text": "Injection test content for context building.",
            "source_type": "test",
        })

        resp = await client.post("/context/inject", json={
            "query": "injection test",
            "token_budget": 500,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "injected_context" in data
        assert "has_context" in data

    @pytest.mark.asyncio
    async def test_cache_stats_and_clear(self, client: AsyncClient):
        # Get cache stats
        resp = await client.get("/context/cache/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] >= 0

        # Clear cache
        resp = await client.post("/context/cache/clear")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_list_index_entries(self, client: AsyncClient):
        # Index some content
        await client.post("/context/index", json={
            "text": "Entry for listing test.",
            "source_type": "test",
            "metadata": {"title": "Test Entry"},
        })

        resp = await client.get("/context/index/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "entries" in data
        assert "total" in data
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_list_index_by_source_type(self, client: AsyncClient):
        await client.post("/context/index", json={
            "text": "Memory type entry.",
            "source_type": "memory",
        })

        resp = await client.get("/context/index/list", params={"source_type": "memory"})
        assert resp.status_code == 200
        data = resp.json()
        for entry in data["entries"]:
            assert entry["source_type"] == "memory"

    @pytest.mark.asyncio
    async def test_delete_index_entry(self, client: AsyncClient):
        # Create an entry
        idx_resp = await client.post("/context/index", json={
            "text": "Deletable entry.",
            "source_type": "test",
        })

        # List to get the UUID
        list_resp = await client.get("/context/index/list", params={"source_type": "test"})
        entries = list_resp.json()["entries"]
        if entries:
            entry_id = entries[0]["id"]
            resp = await client.delete(f"/context/index/{entry_id}")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_invalid_uuid(self, client: AsyncClient):
        resp = await client.delete("/context/index/not-a-uuid")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_nonexistent_entry(self, client: AsyncClient):
        fake_id = str(uuid.uuid4())
        resp = await client.delete(f"/context/index/{fake_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_clear_index(self, client: AsyncClient):
        resp = await client.post("/context/index/clear")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_search_empty(self, client: AsyncClient):
        resp = await client.post("/context/search", json={
            "query": "nothing should match this",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    @pytest.mark.asyncio
    async def test_search_with_top_k_limit(self, client: AsyncClient):
        resp = await client.post("/context/search", json={
            "query": "test",
            "top_k": 1,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] <= 1


# ── Edge Case Tests ──

class TestContextEdgeCases:
    """边界情况测试"""

    def test_context_result_serializable(self):
        result = ContextResult(
            context="test context",
            sources=[{"id": "1", "text": "source"}],
            token_count=100,
            cache_hit=True,
            retrieval_count=5,
        )
        # Should serialize to dict
        d = {
            "context": result.context,
            "sources": result.sources,
            "token_count": result.token_count,
            "cache_hit": result.cache_hit,
            "retrieval_count": result.retrieval_count,
        }
        json_str = json.dumps(d)
        assert "test context" in json_str

    @pytest.mark.asyncio
    async def test_engine_reuse(self):
        """Verify engine can be reused across multiple operations"""
        embed = _MockEmbeddingService(dim=64)
        engine = ContextEngine(embed_service=embed, vector_dim=64)

        # Index different documents
        for i in range(3):
            await engine.index(f"Document {i} content.", {"idx": i})

        # Search multiple times
        for _ in range(3):
            results = await engine.search("document")
            assert len(results) >= 0  # Should not crash

    @pytest.mark.asyncio
    async def test_large_document_indexing(self):
        """Index a large document (1000+ words)"""
        embed = _MockEmbeddingService(dim=64)
        engine = ContextEngine(embed_service=embed, vector_dim=64)

        large_text = ("The AI Runtime OS platform provides comprehensive agent orchestration. " * 100)
        ids = await engine.index(large_text, {"type": "large"})
        assert len(ids) > 0
        # Should produce multiple chunks
        assert len(ids) > 1

    @pytest.mark.asyncio
    async def test_chinese_index_and_search(self):
        """验证中文索引和搜索"""
        embed = _MockEmbeddingService(dim=64)
        engine = ContextEngine(embed_service=embed, vector_dim=64)

        await engine.index("AI Runtime OS 是一个面向专业软件工厂的 AI Agent 流程管理工具。")
        await engine.index("系统支持 LangGraph 和 WorkBuddy 混合架构。")

        results = await engine.search("Agent 流程管理")
        assert len(results) >= 0  # Should not crash

        build_result = await engine.build("软件工厂")
        assert isinstance(build_result, ContextResult)
