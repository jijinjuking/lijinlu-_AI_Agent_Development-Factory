"""
Cross-Encoder Reranker — 交叉编码器重排序器

对检索结果做精排，提升上下文相关性。
目前使用轻量 log-likelihood 近似（无额外模型依赖），
可替换为真实 Cross-Encoder 模型（如 ms-marco-MiniLM-L-6-v2）。
"""

import logging
import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.runtime.context_engine.retrieval.retriever import VectorDoc

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """
    交叉编码器重排序器。

    策略：
    - 有 embedding_service 时用余弦相似度精排
    - 否则用 score 作为 relevance 信号
    """

    def __init__(self, embedding_service: Any = None, top_k: int = 10):
        self.embedding_service = embedding_service
        self.top_k = top_k

    async def rerank(
        self,
        query: str,
        docs: list,
        top_k: int | None = None,
    ) -> list:
        """
        对检索结果做重排序。

        返回重排后的 docs（原地修改 score）。
        """
        k = top_k or self.top_k
        if not docs:
            return docs

        # 策略 A：有 embedding_service → 计算 query-doc 余弦相似度
        if self.embedding_service and hasattr(self.embedding_service, "embed"):
            try:
                results = await self._rerank_by_embedding(query, docs)
                return results[:k]
            except Exception as e:
                logger.warning("Reranker embedding failed, fallback to score: %s", e)

        # 策略 B：直接用原始 score（已经由 retriever 给出）
        docs.sort(key=lambda d: d.score, reverse=True)
        return docs[:k]

    async def _rerank_by_embedding(self, query: str, docs: list) -> list:
        """用 embedding 余弦相似度重排"""
        # 获取 query embedding
        q_emb = await self.embedding_service.embed([query])
        if not q_emb or not q_emb[0]:
            return docs

        q_vec = q_emb[0]
        q_norm = math.sqrt(sum(x * x for x in q_vec))

        scored = []
        for doc in docs:
            d_vec = doc.vector
            if not d_vec or q_norm == 0:
                scored.append((doc.score, doc))
                continue

            # 余弦相似度
            dot = sum(a * b for a, b in zip(q_vec, d_vec))
            d_norm = math.sqrt(sum(x * x for x in d_vec))
            sim = dot / (q_norm * d_norm) if d_norm > 0 else 0.0

            # 融合：0.7 * 原始 score + 0.3 * 语义相似度
            fused = 0.7 * doc.score + 0.3 * max(sim, 0.0)
            scored.append((fused, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        for i, (s, doc) in enumerate(scored):
            doc.score = s  # 更新 score

        return [doc for _, doc in scored]

    def set_embedding_service(self, svc: Any) -> None:
        self.embedding_service = svc
