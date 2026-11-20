"""
ArtifactStore — 产物存储核心
文件系统存内容，SQLite 存元数据。
接口设计兼容未来切换 MinIO（只需改 store.py）。
"""
from __future__ import annotations

import logging
import os
import uuid
import difflib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import Artifact
from app.core.event_bus import event_bus, Event
from app.core.event_types import EventType

logger = logging.getLogger("ai_runtime_os.artifact_store")

# 产物存储根目录（相对于项目根）
DATA_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "data" / "artifacts"

ARTIFACT_TYPES = frozenset({
    "requirement_doc", "architecture_doc", "code_file", "code_patch",
    "test_result", "review_report", "deploy_log", "browser_screenshot",
    "runtime_trace", "context_snapshot",
})

# 产物大小限制 10MB
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024


def _build_storage_path(task_id: str, artifact_type: str, artifact_id: str) -> Path:
    return DATA_ROOT / task_id / artifact_type / artifact_id


class ArtifactStore:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── 保存 ──

    async def save(
        self,
        task_id: str,
        artifact_type: str,
        content: str | bytes,
        metadata: dict[str, Any] | None = None,
        parent_artifact_id: str | None = None,
    ) -> str:
        """保存 Artifact，返回 artifact_id"""
        if artifact_type not in ARTIFACT_TYPES:
            raise ValueError(f"Unsupported artifact_type: {artifact_type}")

        if isinstance(content, str):
            raw = content.encode("utf-8")
        else:
            raw = content

        if len(raw) > MAX_ARTIFACT_BYTES:
            raise ValueError(f"Artifact too large ({len(raw)} bytes > {MAX_ARTIFACT_BYTES})")

        aid = str(uuid.uuid4())
        file_path = _build_storage_path(task_id, artifact_type, aid)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(raw)

        size_bytes = len(raw)

        # 写入元数据
        art = Artifact(
            id=uuid.UUID(aid),
            task_id=uuid.UUID(task_id),
            artifact_type=artifact_type,
            file_path=str(file_path),
            version=1,
            parent_artifact_id=uuid.UUID(parent_artifact_id) if parent_artifact_id else None,
            metadata_json=metadata or {},
            created_by_agent=metadata.get("agent_name") if metadata else None,
        )
        self.db.add(art)
        await self.db.commit()

        # 发布事件
        try:
            await event_bus.publish(Event(
                type=EventType.ARTIFACT_CREATED,
                task_id=task_id,
                payload={
                    "artifact_id": aid,
                    "type": artifact_type,
                    "size_bytes": size_bytes,
                },
                produced_by="artifact_store",
            ))
        except Exception:
            logger.debug("EventBus publish skipped (not initialized)")

        logger.info("Artifact saved: %s (%s, %d bytes)", aid, artifact_type, size_bytes)
        return aid

    # ── 加载 ──

    async def load(self, artifact_id: str) -> str:
        """加载 Artifact 文本内容"""
        meta = await self.get_meta(artifact_id)
        if meta is None:
            raise FileNotFoundError(f"Artifact {artifact_id} not found")
        fp = Path(meta["file_path"])
        if not fp.exists():
            raise FileNotFoundError(f"Artifact file missing: {fp}")
        return fp.read_text(encoding="utf-8")

    async def load_bytes(self, artifact_id: str) -> bytes:
        """加载 Artifact 二进制内容"""
        meta = await self.get_meta(artifact_id)
        if meta is None:
            raise FileNotFoundError(f"Artifact {artifact_id} not found")
        fp = Path(meta["file_path"])
        if not fp.exists():
            raise FileNotFoundError(f"Artifact file missing: {fp}")
        return fp.read_bytes()

    # ── 元数据 ──

    async def get_meta(self, artifact_id: str) -> dict | None:
        stmt = select(Artifact).where(Artifact.id == uuid.UUID(artifact_id))
        res = await self.db.execute(stmt)
        art = res.scalar_one_or_none()
        if art is None:
            return None
        return _artifact_to_dict(art)

    async def list_by_task(self, task_id: str) -> list[dict]:
        stmt = select(Artifact).where(Artifact.task_id == uuid.UUID(task_id)).order_by(Artifact.created_at.desc())
        res = await self.db.execute(stmt)
        return [_artifact_to_dict(a) for a in res.scalars().all()]

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[dict]:
        stmt = select(Artifact).order_by(Artifact.created_at.desc()).limit(limit).offset(offset)
        res = await self.db.execute(stmt)
        return [_artifact_to_dict(a) for a in res.scalars().all()]

    # ── 删除 ──

    async def delete(self, artifact_id: str) -> bool:
        """删除 Artifact（文件 + 元数据）"""
        meta = await self.get_meta(artifact_id)
        if meta is None:
            return False
        fp = Path(meta["file_path"])
        if fp.exists():
            fp.unlink()
        stmt = sa_delete(Artifact).where(Artifact.id == uuid.UUID(artifact_id))
        await self.db.execute(stmt)
        await self.db.commit()
        return True

    # ── Diff ──

    async def diff(self, artifact_id_v1: str, artifact_id_v2: str) -> str:
        """两个 Artifact 版本之间的 unified diff"""
        content_v1 = await self.load(artifact_id_v1)
        content_v2 = await self.load(artifact_id_v2)
        diff_lines = list(difflib.unified_diff(
            content_v1.splitlines(keepends=True),
            content_v2.splitlines(keepends=True),
            fromfile=f"v1/{artifact_id_v1}",
            tofile=f"v2/{artifact_id_v2}",
        ))
        return "".join(diff_lines)

    # ── 版本管理（W23-24）──────────────────────────────

    async def get_version_chain(self, artifact_id: str) -> list[dict]:
        """
        从指定 artifact 向上追溯所有祖先版本，返回完整版本链（从最旧到最新）。
        版本链通过 parent_artifact_id 单向链表结构维护。
        """
        chain: list[dict] = []
        current_id: str | None = artifact_id

        visited: set[str] = set()
        while current_id:
            if current_id in visited:
                break  # 防止循环引用
            visited.add(current_id)

            meta = await self.get_meta(current_id)
            if meta is None:
                break
            chain.append(meta)
            current_id = meta.get("parent_artifact_id")

        chain.reverse()  # 最旧在前
        return chain

    async def create_new_version(
        self,
        parent_artifact_id: str,
        content: str | bytes,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        基于已有 Artifact 创建新版本（版本号 +1）。
        新版本 parent_artifact_id 指向 parent。
        返回新版本的 artifact_id。
        """
        parent_meta = await self.get_meta(parent_artifact_id)
        if parent_meta is None:
            raise FileNotFoundError(f"Parent artifact {parent_artifact_id} not found")

        task_id = parent_meta["task_id"]
        artifact_type = parent_meta["artifact_type"]
        new_version = parent_meta["version"] + 1

        if isinstance(content, str):
            raw = content.encode("utf-8")
        else:
            raw = content

        if len(raw) > MAX_ARTIFACT_BYTES:
            raise ValueError(f"Artifact too large ({len(raw)} bytes > {MAX_ARTIFACT_BYTES})")

        aid = str(uuid.uuid4())
        file_path = _build_storage_path(task_id, artifact_type, aid)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(raw)

        merged_metadata = {**(parent_meta.get("metadata") or {}), **(metadata or {})}

        art = Artifact(
            id=uuid.UUID(aid),
            task_id=uuid.UUID(task_id),
            artifact_type=artifact_type,
            file_path=str(file_path),
            version=new_version,
            parent_artifact_id=uuid.UUID(parent_artifact_id),
            metadata_json=merged_metadata,
            created_by_agent=merged_metadata.get("agent_name"),
        )
        self.db.add(art)
        await self.db.commit()

        try:
            await event_bus.publish(Event(
                type=EventType.ARTIFACT_CREATED,
                task_id=task_id,
                payload={"artifact_id": aid, "type": artifact_type, "version": new_version},
                produced_by="artifact_store",
            ))
        except Exception:
            logger.debug("EventBus publish skipped")

        logger.info("New version saved: %s v%d (parent=%s)", aid, new_version, parent_artifact_id)
        return aid

    async def rollback_to(
        self,
        target_artifact_id: str,
        task_id: str | None = None,
    ) -> str:
        """
        回滚到指定版本：读取目标版本内容，创建为最新版本（版本号再 +1）。
        返回新创建的 artifact_id（代表「回滚后的当前版本」）。
        """
        target_meta = await self.get_meta(target_artifact_id)
        if target_meta is None:
            raise FileNotFoundError(f"Target artifact {target_artifact_id} not found")

        content_bytes = await self.load_bytes(target_artifact_id)

        rollback_metadata = {
            **(target_meta.get("metadata") or {}),
            "rollback_from": target_artifact_id,
            "rollback_from_version": target_meta["version"],
        }

        new_id = await self.create_new_version(
            parent_artifact_id=target_artifact_id,
            content=content_bytes,
            metadata=rollback_metadata,
        )

        logger.info(
            "Rollback completed: new=%s (from v%d/%s)",
            new_id, target_meta["version"], target_artifact_id,
        )
        return new_id

    # ── 统计 ──

    async def count(self) -> int:
        from sqlalchemy import func
        stmt = select(func.count()).select_from(Artifact)
        res = await self.db.execute(stmt)
        return res.scalar() or 0

    async def total_size_bytes(self) -> int:
        artifacts = await self.list_all(limit=10000)
        total = 0
        for a in artifacts:
            fp = Path(a["file_path"])
            if fp.exists():
                total += fp.stat().st_size
        return total


def _artifact_to_dict(a: Artifact) -> dict:
    return {
        "id": str(a.id),
        "task_id": str(a.task_id) if a.task_id else None,
        "artifact_type": a.artifact_type,
        "file_path": a.file_path,
        "version": a.version,
        "parent_artifact_id": str(a.parent_artifact_id) if a.parent_artifact_id else None,
        "metadata": a.metadata_json,
        "created_by_agent": a.created_by_agent,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
