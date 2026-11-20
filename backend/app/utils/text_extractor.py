"""
AI Runtime OS — 文本提取工具
从上传的文件中提取文本内容（支持 TXT/MD/DOCX/PDF）
"""
from __future__ import annotations

from pathlib import Path


def extract_text_from_file(file_path: str, file_type: str) -> str:
    """
    根据文件类型提取文本内容。

    Args:
        file_path: 文件物理路径
        file_type: 文件类型（txt / md / docx / pdf）

    Returns:
        提取的文本内容

    Raises:
        ValueError: 不支持的文件类型
    """
    file_type = file_type.lower()

    if file_type in ("txt", "md"):
        return _extract_text_from_plain(file_path)

    elif file_type == "docx":
        return _extract_text_from_docx(file_path)

    elif file_type == "pdf":
        return _extract_text_from_pdf(file_path)

    else:
        raise ValueError(f"不支持的文件类型: {file_type}")


def _extract_text_from_plain(file_path: str) -> str:
    """提取纯文本文件内容"""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _extract_text_from_docx(file_path: str) -> str:
    """提取 DOCX 文件内容（使用 python-docx）"""
    from docx import Document

    doc = Document(file_path)
    parts: list[str] = []

    # 提取所有段落
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)

    # 提取表格内容
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text)

    return "\n".join(parts)


def _extract_text_from_pdf(file_path: str) -> str:
    """提取 PDF 文件内容（使用 PyPDF2）"""
    from PyPDF2 import PdfReader

    parts: list[str] = []

    with open(file_path, "rb") as f:
        reader = PdfReader(f)
        for page in reader.pages:
            text = page.extract_text()
            if text and text.strip():
                parts.append(text)

    return "\n".join(parts)
