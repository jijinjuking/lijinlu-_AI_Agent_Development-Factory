"""
AI Runtime OS — 轻量 State Manager + Artifact Store
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import settings

# ---- State Manager ----

# Phase 1: 内存 State 存储（50KB 限制）
_state_store: dict[str, dict] = {}
_STATE_MAX_SIZE = 50_000  # 50KB


class StateTooLargeError(Exception):
    """State 超过大小限制"""
    pass


class StateManager:
    """
    轻量 State 管理。
    核心原则：State 只存 reference（artifact_refs, context_refs），不存内容。
    """

    async def load(self, task_id: str) -> dict:
        """加载 State"""
        return _state_store.get(task_id, {"task_id": task_id, "artifact_refs": [], "current_node": ""})

    async def save(self, task_id: str, state: dict) -> None:
        """保存 State，校验大小"""
        size = len(json.dumps(state, default=str))
        if size > _STATE_MAX_SIZE:
            ref_count = len(state.get("artifact_refs", []))
            raise StateTooLargeError(
                f"State 过大 ({size}B > {_STATE_MAX_SIZE}B)，请将内容移到 Artifact Store。"
                f"当前 artifact_refs: {ref_count} 个。"
            )
        _state_store[task_id] = state

    async def delete(self, task_id: str) -> None:
        _state_store.pop(task_id, None)

    async def update_status(self, task_id: str, status: str) -> None:
        state = await self.load(task_id)
        state["workflow_status"] = status
        await self.save(task_id, state)


# ---- Artifact Store ----

class ArtifactStore:
    """
    Artifact 存储。
    Phase 1: 本地文件系统存储。
    Phase 2: MinIO / S3 存储。
    """

    def __init__(self, base_dir: str | None = None):
        if base_dir:
            self._base = Path(base_dir)
        else:
            # 放在项目 backend 目录下
            self._base = Path(__file__).resolve().parent.parent.parent / "artifacts"
        self._base.mkdir(parents=True, exist_ok=True)

    async def save(
        self, task_id: str, artifact_type: str, content: str, metadata: dict | None = None
    ) -> str:
        """保存 Artifact，返回 artifact_id"""
        aid = str(uuid4())
        subdir = self._base / task_id / artifact_type
        subdir.mkdir(parents=True, exist_ok=True)
        file_path = subdir / aid

        if isinstance(content, str):
            file_path.write_text(content, encoding="utf-8")
        else:
            file_path.write_bytes(content)

        # 写元数据
        meta = metadata or {}
        meta["artifact_id"] = aid
        meta["task_id"] = task_id
        meta["artifact_type"] = artifact_type
        meta_path = file_path.with_suffix(".meta.json")
        meta_path.write_text(json.dumps(meta, default=str, ensure_ascii=False), encoding="utf-8")

        return aid

    async def load(self, task_id: str, artifact_id: str) -> str | None:
        """加载 Artifact 内容"""
        # 遍历查找（简单实现）
        for subdir in self._base.glob(f"{task_id}/*"):
            if subdir.is_dir():
                file_path = subdir / artifact_id
                if file_path.exists():
                    return file_path.read_text(encoding="utf-8")
        return None

    async def list_by_task(self, task_id: str) -> list[dict]:
        """列出某个任务的所有 Artifact"""
        result = []
        task_dir = self._base / task_id
        if not task_dir.exists():
            return result
        for meta_file in task_dir.glob("*/*.meta.json"):
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            result.append(meta)
        return result


# 全局单例
state_manager = StateManager()
artifact_store = ArtifactStore()
