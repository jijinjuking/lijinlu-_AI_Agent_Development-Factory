"""
Hybrid Retriever — 混合检索器
组合向量检索 + 关键词检索，融合排序
"""
from __future__ import annotations

import logging
import re
from collections import Counter

import numpy as np

from app.services.embedding_service import EmbeddingService
from .vector_store import VectorStore, VectorDoc

logger = logging.getLogger(__name__)


class HybridRetriever:
    """
    混合检索器。
    - Vector Search:  语义相似度（FAISS Inner Product）
    - Keyword Search:  BM25 简化版（TF 加权 + 文档频率）
    - Fusion:         RRF (Reciprocal Rank Fusion) 或线性加权
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_service: EmbeddingService,
        vector_weight: float = 0.7,
    ):
        self.vector_store = vector_store
        self.embedding_service = embedding_service
        self.vector_weight = vector_weight

    async def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
        filters: dict | None = None,
    ) -> list[VectorDoc]:
        """混合检索主入口"""
        # 1. 向量检索
        query_vec = await self.embedding_service.embed_query(query)
        vector_results = await self.vector_store.search(query_vec, top_k=max(top_k * 2, 10))

        # 2. 关键词检索
        keyword_results = self._keyword_search(query, top_k=max(top_k * 2, 10))

        # 3. 应用过滤
        if filters:
            vector_results = self._apply_filters(vector_results, filters)
            keyword_results = self._apply_filters(keyword_results, filters)

        # 4. 融合排序 (RRF)
        fused = self._rrf_fusion(vector_results, keyword_results, k=60)

        # 5. 截断 Top-K
        results = fused[:top_k]
        for doc in results:
            if doc.score < min_score:
                break

        logger.debug("HybridRetriever: query='%s', vector=%d, keyword=%d, fused=%d",
                     query[:50], len(vector_results), len(keyword_results), len(results))
        return results

    def _keyword_search(self, query: str, top_k: int = 10) -> list[VectorDoc]:
        """
        简化 BM25 关键词检索。
        对 query 分词后，计算每个文档与 query 的 TF 重叠分数。
        """
        query_terms = self._tokenize(query)
        if not query_terms:
            return []

        # 计算 query 词频
        query_tf = Counter(query_terms)

        # 对每个文档评分
        scored: list[tuple[VectorDoc, float]] = []
        for doc in self.vector_store._docs.values():
            doc_terms = self._tokenize(doc.text)
            doc_tf = Counter(doc_terms)

            # TF 重叠分数
            score = 0.0
            for term in query_terms:
                if term in doc_tf:
                    # TF * IDF（简化：IDF=1）
                    score += min(query_tf[term], doc_tf[term])

            # 归一化（按文档长度）
            if doc_terms:
                score /= (1 + 0.1 * len(doc_terms))

            if score > 0:
                scored.append((doc, score))

        # 排序
        scored.sort(key=lambda x: x[1], reverse=True)
        return [doc for doc, _ in scored[:top_k]]

    def _rrf_fusion(
        self, results_a: list[VectorDoc], results_b: list[VectorDoc], k: int = 60
    ) -> list[VectorDoc]:
        """
        Reciprocal Rank Fusion。
        对两个排序列表融合，返回混合排序结果。
        """
        scores: dict[str, float] = {}
        doc_map: dict[str, VectorDoc] = {}

        for rank, doc in enumerate(results_a, start=1):
            doc_id = doc.id
            scores[doc_id] = scores.get(doc_id, 0) + self.vector_weight / (k + rank)
            if doc_id not in doc_map:
                doc_map[doc_id] = doc

        kw_weight = 1.0 - self.vector_weight
        for rank, doc in enumerate(results_b, start=1):
            doc_id = doc.id
            scores[doc_id] = scores.get(doc_id, 0) + kw_weight / (k + rank)
            if doc_id not in doc_map:
                doc_map[doc_id] = doc

        # 按融合分数排序
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        results = []
        for doc_id in sorted_ids:
            doc = doc_map[doc_id]
            doc.score = scores[doc_id]
            results.append(doc)

        return results

    def _tokenize(self, text: str) -> list[str]:
        """简单分词：中文字符 + 英文单词"""
        # 提取中文词（按 2-gram）
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        cn_bigrams = [''.join(chinese_chars[i:i+2]) for i in range(len(chinese_chars) - 1)]

        # 提取英文单词
        english_words = re.findall(r'[a-zA-Z0-9_]+', text.lower())

        return cn_bigrams + english_words + chinese_chars

    def _apply_filters(self, docs: list[VectorDoc], filters: dict) -> list[VectorDoc]:
        """应用元数据过滤"""
        result = []
        for doc in docs:
            match = True
            for key, value in filters.items():
                if doc.metadata.get(key) != value:
                    match = False
                    break
            if match:
                result.append(doc)
        return result
