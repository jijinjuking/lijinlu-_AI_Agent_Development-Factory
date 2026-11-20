"""
LLM Compressor — LLM 摘要压缩

超出 Token Budget 时，调用 LLM 对检索结果做摘要压缩。
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.runtime.context_engine.retrieval.retriever import VectorDoc

logger = logging.getLogger(__name__)


@dataclass
class CompressionResult:
    """压缩结果"""
    compressed_text: str
    original_tokens: int = 0
    compressed_tokens: int = 0
    method: str = "llm"
    metadata: dict = field(default_factory=dict)


class LLMCompressor:
    """
    LLM 摘要压缩器。

    当检索结果超出 Token Budget 时，
    调用 LLM 生成摘要式压缩文本。
    """

    PROMPT_TEMPLATE = """\
你是上下文压缩助手。请将以下 {count} 段检索结果压缩为一段连贯的摘要，
保留所有关键事实、数字和结论，控制在 {max_tokens} token 以内。

检索结果：
{docs}

只输出压缩后的摘要文本，不要额外解释。
"""

    def __init__(
        self,
        llm_service: Any = None,
        max_llm_tokens: int = 512,
        fallback_ratio: float = 0.5,
    ):
        """
        Args:
            llm_service: 可选，LLM 调用接口（async callable）
            max_llm_tokens: LLM 压缩后最大 token 数
            fallback_ratio: 无法调用 LLM 时保留的原始文本比例
        """
        self.llm_service = llm_service
        self.max_llm_tokens = max_llm_tokens
        self.fallback_ratio = fallback_ratio

    async def compress(
        self,
        docs: list,
        max_tokens: int,
        llm_service: Any = None,
    ) -> CompressionResult:
        """
        压缩检索结果。

        Args:
            docs: VectorDoc 列表
            max_tokens: 目标最大 token 数
            llm_service: 可选，覆盖初始化时的 llm_service
        """
        original_tokens = sum(getattr(d, "token_count", 0) for d in docs)
        svc = llm_service or self.llm_service

        if svc and hasattr(svc, "generate"):
            try:
                result = await self._compress_by_llm(docs, max_tokens, svc)
                return result
            except Exception as e:
                logger.warning("LLM compression failed, fallback to extractive: %s", e)

        # Fallback：抽取式压缩
        return await self._extractive_compress(docs, max_tokens)

    async def _compress_by_llm(
        self, docs: list, max_tokens: int, svc: Any,
    ) -> CompressionResult:
        """调用 LLM 做摘要压缩"""
        docs_text = "\n\n".join(
            f"[Doc {i+1}] {d.text[:500]}" for i, d in enumerate(docs)
        )
        prompt = self.PROMPT_TEMPLATE.format(
            count=len(docs), max_tokens=max_tokens, docs=docs_text,
        )

        compressed = await svc.generate(prompt, max_tokens=max_tokens)
        compressed = compressed.strip()

        # 估算压缩后 token 数
        compressed_tokens = len(compressed) // 4  # 粗糙估算

        return CompressionResult(
            compressed_text=compressed,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            method="llm",
            metadata={"doc_count": len(docs)},
        )

    async def _extractive_compress(
        self, docs: list, max_tokens: int,
    ) -> CompressionResult:
        """
        抽取式压缩（Fallback）。

        按 score 排序，截取到 token budget 为止。
        """
        sorted_docs = sorted(docs, key=lambda d: d.score, reverse=True)
        parts = []
        used = 0
        for d in sorted_docs:
            t = getattr(d, "token_count", len(d.text) // 4)
            if used + t > max_tokens:
                # 截断最后一段
                remaining = max_tokens - used
                if remaining > 50:
                    parts.append(d.text[:remaining * 4])
                break
            parts.append(d.text)
            used += t

        result_text = "\n\n".join(parts)
        return CompressionResult(
            compressed_text=result_text,
            original_tokens=original_tokens,
            compressed_tokens=used,
            method="extractive_fallback",
            metadata={"doc_count": len(parts)},
        )

    def set_llm_service(self, svc: Any) -> None:
        self.llm_service = svc
