"""
AI Runtime OS — 文件存储工具
保存/删除 Issue 附件的物理文件
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from fastapi import UploadFile

# 项目根目录（backend/ 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ATTACHMENTS_DIR = BASE_DIR / "data" / "issue_attachments"


async def save_upload_file(
    upload_file: UploadFile,
    issue_id: str,
    attachment_id: str,
) -> tuple[str, str, int]:
    """
    保存上传文件到本地存储。

    目录结构：data/issue_attachments/{issue_id}/{attachment_id}/{filename}

    返回：
        (file_path, content_hash, file_size)
    """
    dir_path = ATTACHMENTS_DIR / issue_id / attachment_id
    dir_path.mkdir(parents=True, exist_ok=True)

    file_path = dir_path / upload_file.filename

    # 读取文件内容
    content = await upload_file.read()

    # 写入文件
    file_path.write_bytes(content)

    # 计算 SHA256
    content_hash = hashlib.sha256(content).hexdigest()
    file_size = len(content)

    # 返回相对路径（存数据库用）
    rel_path = f"data/issue_attachments/{issue_id}/{attachment_id}/{upload_file.filename}"
    return rel_path, content_hash, file_size


def delete_attachment_file(issue_id: str, attachment_id: str) -> None:
    """删除附件物理文件目录"""
    dir_path = ATTACHMENTS_DIR / issue_id / attachment_id
    if dir_path.exists():
        shutil.rmtree(dir_path)


def get_attachment_file_path(issue_id: str, attachment_id: str, filename: str) -> Path:
    """获取附件物理文件路径（用于下载）"""
    return ATTACHMENTS_DIR / issue_id / attachment_id / filename
