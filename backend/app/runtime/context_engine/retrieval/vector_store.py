"""
FAISS Vector Store — 内存向量存储
支持 add / search / delete / save / load
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

try:
    import faiss
    _FAISS_AVAILABLE = True
except ImportError:
    _FAISS_AVAILABLE = False
    faiss = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class VectorDoc:
    """向量文档"""
    id: str
    vector: np.ndarray
    text: str
    metadata: dict = field(default_factory=dict)
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "metadata": self.metadata,
            "score": self.score,
        }


class VectorStore:
    """
    FAISS 向量存储封装。
    Phase 1: 内存模式，支持 save/load 到磁盘。
    Phase 2: 可替换为 Qdrant。
    """

    def __init__(self, dim: int = 1536, index_path: str | None = None):
        self.dim = dim
        self.index_path = index_path

        # 核心数据结构
        self._docs: dict[str, VectorDoc] = {}  # id → doc
        self._id_to_idx: dict[str, int] = {}   # id → FAISS index
        self._idx_to_id: dict[int, str] = {}   # FAISS index → id
        self._next_idx: int = 0

        # FAISS 索引
        if _FAISS_AVAILABLE and faiss is not None:
            self._index = faiss.IndexFlatIP(dim)  # Inner Product (cosine after normalization)
        else:
            self._index = None  # Fallback: brute-force numpy

        # 尝试加载已有索引
        if index_path and os.path.exists(index_path):
            self._load(index_path)

    @property
    def count(self) -> int:
        return len(self._docs)

    async def add(
        self, texts: list[str], vectors: np.ndarray,
        metadatas: list[dict] | None = None, ids: list[str] | None = None,
    ) -> list[str]:
        """
        添加文档到向量存储。
        返回文档 ID 列表。
        """
        if len(texts) != len(vectors):
            raise ValueError(f"texts({len(texts)}) and vectors({len(vectors)}) length mismatch")

        metadatas = metadatas or [{}] * len(texts)
        ids = ids or [f"doc_{i}_{np.random.randint(0, 10**9)}" for i in range(len(texts))]

        # L2 归一化（IP 搜索需要）
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors = vectors / norms

        added_ids = []
        for i, (text, vec, meta, doc_id) in enumerate(zip(texts, vectors, metadatas, ids)):
            doc = VectorDoc(id=doc_id, vector=vec, text=text, metadata=meta)
            self._docs[doc_id] = doc
            self._id_to_idx[doc_id] = self._next_idx
            self._idx_to_id[self._next_idx] = doc_id

            if self._index is not None:
                self._index.add(vec.reshape(1, -1))
            self._next_idx += 1
            added_ids.append(doc_id)

        logger.debug("VectorStore: added %d docs, total=%d", len(added_ids), self._next_idx)
        return added_ids

    async def search(
        self, query_vector: np.ndarray, top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[VectorDoc]:
        """
        向量搜索。
        返回最相关的 top_k 个文档（带 score）。
        """
        if self._next_idx == 0:
            return []

        # L2 归一化
        norm = np.linalg.norm(query_vector)
        if norm > 0:
            query_vector = query_vector / norm

        query_vector = query_vector.reshape(1, -1).astype(np.float32)

        if self._index is not None and _FAISS_AVAILABLE:
            scores, indices = self._index.search(query_vector, min(top_k, self._next_idx))
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or idx >= self._next_idx:
                    continue
                if float(score) < min_score:
                    continue
                doc_id = self._idx_to_id.get(int(idx))
                if doc_id and doc_id in self._docs:
                    doc = self._docs[doc_id]
                    doc.score = float(score)
                    results.append(doc)
            return results
        else:
            # Numpy fallback: 余弦相似度
            all_vectors = np.array([d.vector for d in self._docs.values()])
            similarities = np.dot(all_vectors, query_vector.T).flatten()
            top_indices = np.argsort(similarities)[::-1][:top_k]

            results = []
            for idx in top_indices:
                score = float(similarities[idx])
                if score < min_score:
                    continue
                doc_id = self._idx_to_id.get(int(idx))
                if doc_id and doc_id in self._docs:
                    doc = self._docs[doc_id]
                    doc.score = score
                    results.append(doc)
            return results

    async def delete(self, ids: list[str]) -> int:
        """删除文档（FAISS 不支持直接删除，标记为逻辑删除）"""
        deleted = 0
        for doc_id in ids:
            if doc_id in self._docs:
                del self._docs[doc_id]
                if doc_id in self._id_to_idx:
                    del self._id_to_idx[doc_id]
                deleted += 1
        logger.debug("VectorStore: deleted %d docs", deleted)
        return deleted

    async def get(self, doc_id: str) -> VectorDoc | None:
        """获取单个文档"""
        return self._docs.get(doc_id)

    async def list_docs(self, limit: int = 100, offset: int = 0) -> list[VectorDoc]:
        """列出文档"""
        docs = list(self._docs.values())[offset:offset + limit]
        return docs

    # ---- 持久化 ----

    def save(self, path: str | None = None):
        """保存索引到磁盘"""
        save_path = path or self.index_path
        if not save_path:
            raise ValueError("No save path specified")

        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        # 保存 FAISS 索引
        if self._index is not None and _FAISS_AVAILABLE:
            faiss.write_index(self._index, save_path + ".faiss")

        # 保存元数据
        meta = {
            "dim": self.dim,
            "next_idx": self._next_idx,
            "docs": {
                doc_id: {
                    "id": doc.id,
                    "text": doc.text,
                    "metadata": doc.metadata,
                }
                for doc_id, doc in self._docs.items()
            },
            "id_to_idx": self._id_to_idx,
        }
        with open(save_path + ".meta", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        logger.info("VectorStore: saved %d docs to %s", len(self._docs), save_path)

    def _load(self, path: str):
        """从磁盘加载索引"""
        meta_path = path + ".meta"
        faiss_path = path + ".faiss"

        if not os.path.exists(meta_path):
            logger.warning("VectorStore: meta file not found: %s", meta_path)
            return

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        self.dim = meta.get("dim", self.dim)
        self._next_idx = meta.get("next_idx", 0)
        self._id_to_idx = {k: int(v) for k, v in meta.get("id_to_idx", {}).items()}

        for doc_id, doc_data in meta.get("docs", {}).items():
            self._docs[doc_id] = VectorDoc(
                id=doc_data["id"],
                vector=np.zeros(self.dim, dtype=np.float32),  # 占位
                text=doc_data["text"],
                metadata=doc_data.get("metadata", {}),
            )

        # 加载 FAISS 索引
        if os.path.exists(faiss_path) and _FAISS_AVAILABLE and faiss is not None:
            self._index = faiss.read_index(faiss_path)

        # 重建 idx_to_id
        self._idx_to_id = {v: k for k, v in self._id_to_idx.items()}

        logger.info("VectorStore: loaded %d docs from %s", len(self._docs), path)

    async def clear(self):
        """清空所有数据"""
        self._docs.clear()
        self._id_to_idx.clear()
        self._idx_to_id.clear()
        self._next_idx = 0
        if _FAISS_AVAILABLE and faiss is not None:
            self._index = faiss.IndexFlatIP(self.dim)
