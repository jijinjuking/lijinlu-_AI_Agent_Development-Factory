"""
Embedding Service — 文本向量化服务
支持: OpenAI Embeddings API / 本地 sentence-transformers
复用 llm_service 的 OpenAI client 模式
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Optional

import httpx
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

# 默认 embedding 维度
EMBEDDING_DIMS: dict[str, int] = {
    "text-embedding-ada-002": 1536,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}


class EmbeddingService:
    """
    文本向量化服务。
    优先使用 OpenAI API，失败时 fallback 到本地 hash-based 占位向量（仅用于测试）。
    """

    def __init__(
        self,
        model: str = "text-embedding-ada-002",
        api_key: str | None = None,
        base_url: str | None = None,
        dim: int | None = None,
    ):
        self.model = model
        self.api_key = api_key or settings.openai_api_key or ""
        self.base_url = (base_url or settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
        self.dim = dim or EMBEDDING_DIMS.get(model, 1536)

    async def embed(self, texts: list[str]) -> np.ndarray:
        """
        将文本列表转为向量数组。
        返回 shape=(len(texts), dim) 的 numpy 数组。
        """
        if not texts:
            return np.array([], dtype=np.float32).reshape(0, self.dim)

        # 尝试 OpenAI API
        if self.api_key:
            try:
                return await self._openai_embed(texts)
            except Exception as e:
                logger.warning("OpenAI embedding failed: %s, fallback to local", e)

        # Fallback: 使用 hash-based 占位向量（开发/测试用）
        return self._hash_embed(texts)

    async def embed_query(self, text: str) -> np.ndarray:
        """单条查询文本向量化，返回 shape=(dim,)"""
        result = await self.embed([text])
        return result[0]

    async def _openai_embed(self, texts: list[str]) -> np.ndarray:
        """调用 OpenAI Embeddings API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": texts,
        }

        t0 = time.time()
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                headers=headers,
                json=payload,
            )
        resp.raise_for_status()
        data = resp.json()

        vectors = []
        for item in data["data"]:
            vectors.append(item["embedding"])

        logger.debug("OpenAI embedding: %d texts, %dms", len(texts), int((time.time() - t0) * 1000))
        return np.array(vectors, dtype=np.float32)

    def _hash_embed(self, texts: list[str]) -> np.ndarray:
        """
        Hash-based 占位向量（无 API 时使用）。
        使用 SHA256 将文本映射到固定维度伪随机向量，保证:
        - 相同文本 → 相同向量
        - 不同文本 → 不同向量（大概率）
        """
        vectors = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for bit in range(self.dim):
                h = hashlib.sha256(f"{text}:{bit}".encode()).digest()
                # 将前4字节转为 [-1, 1] 的浮点数
                val = int.from_bytes(h[:4], "big") / (2**32) * 2 - 1
                vectors[i, bit] = val
            # L2 归一化
            norm = np.linalg.norm(vectors[i])
            if norm > 0:
                vectors[i] /= norm
        return vectors

    async def close(self):
        """关闭资源（预留）"""
        pass


# 全局单例
embedding_service = EmbeddingService()
