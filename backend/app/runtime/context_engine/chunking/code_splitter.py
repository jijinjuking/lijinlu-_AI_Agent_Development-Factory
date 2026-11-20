"""
Code Splitter — 语法感知代码分块器

基于 AST 解析做代码分块，保持语法完整性。
支持 Python/JavaScript/TypeScript/Java/C/C++/Go。
"""

import ast
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.runtime.context_engine.chunking import TextSplitter, Chunk

logger = logging.getLogger(__name__)

# 支持的语言
SUPPORTED_LANGUAGES = {
    "python", "javascript", "typescript", "java",
    "c", "cpp", "go", "rust", "ruby", "php",
}


@dataclass
class CodeChunk(Chunk):
    """代码分块结果"""
    language: str = ""
    start_line: int = 0
    end_line: int = 0
    ast_node_type: str = ""   # function/class/method/other
    symbols: list[str] = field(default_factory=list)  # 函数名/类名等


class CodeSplitter(TextSplitter):
    """
    语法感知代码分块器。

    策略（按优先级）：
    1. AST 解析 → 按 function/class 分块
    2. fallback：按逻辑段落（空行分隔）
    3. fallback：按字符数硬切
    """

    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        language: str = "python",
        preserve_comments: bool = True,
        include_docstrings: bool = True,
    ):
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.language = language.lower()
        self.preserve_comments = preserve_comments
        self.include_docstrings = include_docstrings

    def split_text(
        self, text: str, metadata: dict | None = None
    ) -> list[Chunk]:
        """
        分块入口。
        优先尝试 AST 分块，失败则 fallback。
        """
        metadata = metadata or {}
        lang = metadata.get("language", self.language).lower()

        if lang == "python":
            try:
                return self._split_python_ast(text, metadata)
            except SyntaxError:
                logger.warning("Python AST parse failed, fallback to logical split")
                return self._split_logical(text, metadata)

        # 其他语言暂用 logical split
        return self._split_logical(text, metadata)

    def _split_python_ast(self, text: str, metadata: dict) -> list[Chunk]:
        """Python AST 分块：按 function/class 切割"""
        tree = ast.parse(text)
        lines = text.splitlines(keepends=True)

        chunks: list[CodeChunk] = []
        # 收集顶层 function/class 节点
        nodes = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nodes.append((node.lineno, node.end_lineno, node))

        if not nodes:
            # 无结构化节点，整体作为一块
            return [CodeChunk(
                text=text,
                metadata={**metadata, "language": "python",
                          "ast_node_type": "module"},
            )]

        # 按节点分块
        nodes.sort(key=lambda x: x[0])
        prev_end = 1

        for start, end, node in nodes:
            # 节点前的代码（imports, globals）
            if start > prev_end:
                pre_lines = lines[prev_end - 1: start - 1]
                if pre_lines and "".join(pre_lines).strip():
                    chunks.append(CodeChunk(
                        text="".join(pre_lines),
                        metadata={
                            **metadata, "language": "python",
                            "start_line": prev_end,
                            "end_line": start - 1,
                            "ast_node_type": "header",
                        },
                    ))

            node_lines = lines[start - 1: end]
            node_text = "".join(node_lines)
            node_type = "function" if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) else "class"

            symbols = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols = [node.name]
            elif isinstance(node, ast.ClassDef):
                symbols = [node.name]

            chunks.append(CodeChunk(
                text=node_text,
                metadata={
                    **metadata, "language": "python",
                    "start_line": start,
                    "end_line": end,
                    "ast_node_type": node_type,
                    "symbols": symbols,
                },
            ))
            prev_end = end + 1

        # 文件尾部
        if prev_end <= len(lines):
            tail = "".join(lines[prev_end - 1:])
            if tail.strip():
                chunks.append(CodeChunk(
                    text=tail,
                    metadata={
                        **metadata, "language": "python",
                        "start_line": prev_end,
                        "end_line": len(lines),
                        "ast_node_type": "tail",
                    },
                ))

        # 应用 chunk_size 限制（超大函数再切分）
        return self._enforce_size_limit(chunks)

    def _split_logical(self, text: str, metadata: dict) -> list[Chunk]:
        """
        逻辑段落分块：按空行分隔符切割，
        再按 chunk_size 合并。
        """
        # 切分为逻辑段落（空行分隔）
        paragraphs = re.split(r"\n\s*\n", text)
        chunks: list[CodeChunk] = []
        current_lines: list[str] = []
        current_size = 0
        start_line = 1

        for para in paragraphs:
            para_lines = para.splitlines()
            para_size = sum(len(l) for l in para_lines)

            if current_size + para_size > self.chunk_size and current_lines:
                chunks.append(CodeChunk(
                    text="\n".join(current_lines),
                    metadata={
                        **metadata, "language": metadata.get("language", "unknown"),
                        "start_line": start_line,
                        "end_line": start_line + len(current_lines) - 1,
                    },
                ))
                # 保留 overlap
                overlap_lines = current_lines[-min(len(current_lines),
                                                 self.chunk_overlap // 20):]
                current_lines = overlap_lines
                current_size = sum(len(l) for l in current_lines)
                start_line = start_line + len(current_lines)

            current_lines.extend(para_lines)
            current_size += para_size

        if current_lines:
            chunks.append(CodeChunk(
                text="\n".join(current_lines),
                metadata={
                    **metadata, "language": metadata.get("language", "unknown"),
                    "start_line": start_line,
                    "end_line": start_line + len(current_lines) - 1,
                },
            ))

        return chunks or [CodeChunk(text=text, metadata=metadata)]

    def _enforce_size_limit(self, chunks: list[CodeChunk]) -> list[Chunk]:
        """对超大型 chunk 再做字符数硬切分"""
        result: list[Chunk] = []
        for chunk in chunks:
            if len(chunk.text) <= self.chunk_size:
                result.append(chunk)
            else:
                # 硬切
                text = chunk.text
                for i in range(0, len(text), self.chunk_size - self.chunk_overlap):
                    slice_ = text[i: i + self.chunk_size]
                    result.append(Chunk(
                        text=slice_,
                        metadata={
                            **chunk.metadata,
                            "chunk_index": len(result),
                            "is_sub_chunk": True,
                        },
                    ))
        return result

    def count_tokens(self, text: str) -> int:
        """代码 token 估算：字符数 / 3（代码密度更高）"""
        try:
            import tiktoken
            enc = tiktoken.encoding_for_model("gpt-4o")
            return len(enc.encode(text))
        except ImportError:
            return len(text) // 3
