"""
Text Splitter — 文本分块器
支持递归字符分割，基于 tiktoken 估算 token 数
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

try:
    import tiktoken
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_AVAILABLE = False


@dataclass
class Chunk:
    """文本块"""
    text: str
    index: int                          # 块序号
    token_count: int = 0                # 估算 token 数
    metadata: dict = field(default_factory=dict)  # 来源等元信息

    def __repr__(self) -> str:
        return f"Chunk(#{self.index}, {self.token_count} tokens)"


class TextSplitter:
    """
    递归字符文本分块器。
    按优先级尝试分隔符：段落 → 句子 → 空格 → 字符
    """

    # 默认分隔符优先级（从粗到细）
    DEFAULT_SEPARATORS = [
        "\n\n",     # 段落
        "\n",       # 换行
        "。",       # 中文句号
        ". ",       # 英文句号+空格
        "；",       # 中文分号
        "; ",       # 英文分号
        "，",       # 中文逗号
        ", ",       # 英文逗号
        " ",        # 空格
        "",         # 字符级
    ]

    # 代码分隔符优先级
    CODE_SEPARATORS = [
        "\n\n",     # 空行
        "\n",       # 换行
        "    ",     # 缩进
        " ",        # 空格
        "",         # 字符级
    ]

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        separators: list[str] | None = None,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or self.DEFAULT_SEPARATORS

        # Tokenizer（可选）
        self._tokenizer = None
        if _TIKTOKEN_AVAILABLE:
            try:
                self._tokenizer = tiktoken.get_encoding("cl100k_base")
            except Exception:
                pass

    def count_tokens(self, text: str) -> int:
        """估算文本 token 数"""
        if self._tokenizer:
            return len(self._tokenizer.encode(text))
        # Fallback: 英文 1 token ≈ 4 chars, 中文 1 token ≈ 1.5 chars
        cn_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        en_chars = len(text) - cn_chars
        return int(cn_chars / 1.5 + en_chars / 4)

    def split_text(self, text: str, metadata: dict | None = None) -> list[Chunk]:
        """将文本分块，返回 Chunk 列表"""
        if not text.strip():
            return []

        meta = metadata or {}
        chunks: list[Chunk] = []
        texts = self._split_recursive(text, self.separators)

        for i, chunk_text in enumerate(texts):
            chunks.append(Chunk(
                text=chunk_text,
                index=i,
                token_count=self.count_tokens(chunk_text),
                metadata={**meta, "chunk_index": i, "total_chunks": len(texts)},
            ))

        return chunks

    def split_documents(
        self, documents: list[dict], content_key: str = "content"
    ) -> list[Chunk]:
        """批量分块文档（保留文档级别元信息）"""
        all_chunks: list[Chunk] = []
        for doc in documents:
            text = doc.get(content_key, "")
            meta = {k: v for k, v in doc.items() if k != content_key}
            chunks = self.split_text(text, meta)
            all_chunks.extend(chunks)
        return all_chunks

    def _split_recursive(self, text: str, separators: list[str]) -> list[str]:
        """递归分割"""
        result: list[str] = []

        # 找最合适的分隔符
        best_sep = ""
        best_sep_idx = -1
        for sep in separators:
            if sep == "":
                continue
            if sep in text:
                best_sep = sep
                break

        # 无需分割
        if self.count_tokens(text) <= self.chunk_size:
            return [text] if text else []

        if best_sep:
            parts = self._split_by_separator(text, best_sep)
        else:
            # 字符级分割
            parts = list(text)

        # 合并 part 直到达到 chunk_size
        current_chunk = ""
        for part in parts:
            if self.count_tokens(current_chunk + best_sep + part) <= self.chunk_size:
                current_chunk = current_chunk + (best_sep if current_chunk else "") + part
            else:
                if current_chunk:
                    result.append(current_chunk)
                # 如果单个 part 超过 chunk_size，递归分割
                if self.count_tokens(part) > self.chunk_size:
                    sub_parts = self._split_recursive(part, separators[1:] if len(separators) > 1 else [""])
                    result.extend(sub_parts)
                else:
                    current_chunk = part

        if current_chunk:
            result.append(current_chunk)

        # Overlap: 在块之间添加重叠
        if self.chunk_overlap > 0 and len(result) > 1:
            overlapped = []
            for i, chunk in enumerate(result):
                if i == 0:
                    overlapped.append(chunk)
                else:
                    prev = result[i - 1]
                    # 从前一块末尾取 overlap 内容
                    overlap_text = prev[-min(len(prev), self.chunk_overlap * 4):]
                    overlapped.append(overlap_text + "\n" + chunk)
            result = overlapped

        return result

    def _split_by_separator(self, text: str, separator: str) -> list[str]:
        """按分隔符分割，保留非空部分"""
        if separator == "":
            return list(text)
        return [p for p in text.split(separator) if p]
