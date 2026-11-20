"""
Rollback Manager — 文件变更回滚管理

记录 Tool 执行期间的所有文件变更（创建/修改/删除），
支持原子回滚到执行前状态。
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ChangeType(str, Enum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass
class FileChange:
    """单次文件变更记录"""
    change_type: ChangeType
    path: str
    backup_path: str | None = None      # 修改前的备份位置
    original_content: str | None = None  # 创建前无此文件（None）
    timestamp: float = field(default_factory=time.time)


@dataclass
class RollbackResult:
    """回滚结果"""
    success: bool
    changes_rolled_back: int = 0
    changes_failed: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


class RollbackManager:
    """
    回滚管理器。

    用法:
        mgr = RollbackManager()
        snapshot = mgr.create_snapshot("task_123")

        # 执行一些文件操作...
        mgr.record_created("task_123", "/tmp/output.txt")
        mgr.record_modified("task_123", "/tmp/config.json")

        # 出错时回滚
        result = await mgr.rollback("task_123")
    """

    MAX_BACKUP_SIZE = 10 * 1024 * 1024  # 10MB

    def __init__(self):
        self._snapshots: dict[str, list[FileChange]] = {}
        self._rollback_history: dict[str, list[RollbackResult]] = {}

    def create_snapshot(self, task_id: str) -> str:
        """为 task 创建变更快照（开始记录）"""
        self._snapshots[task_id] = []
        logger.debug("RollbackManager: snapshot created for %s", task_id)
        return task_id

    # ---- Recording ----

    def record_created(self, task_id: str, path: str) -> None:
        """记录文件创建"""
        self._ensure_snapshot(task_id)
        self._snapshots[task_id].append(FileChange(
            change_type=ChangeType.CREATED,
            path=path,
            original_content=None,
        ))

    def record_modified(self, task_id: str, path: str) -> bool:
        """记录文件修改（自动备份原文件）。

        返回 True 表示备份成功。
        """
        self._ensure_snapshot(task_id)

        if not os.path.exists(path):
            logger.warning("RollbackManager: cannot backup non-existent file: %s", path)
            return False

        size = os.path.getsize(path)
        if size > self.MAX_BACKUP_SIZE:
            logger.warning("RollbackManager: file too large to backup: %s (%d bytes)", path, size)
            return False

        try:
            # 创建临时备份
            fd, backup_path = tempfile.mkstemp(prefix="rollback_")
            os.close(fd)
            shutil.copy2(path, backup_path)

            self._snapshots[task_id].append(FileChange(
                change_type=ChangeType.MODIFIED,
                path=path,
                backup_path=backup_path,
            ))
            return True
        except Exception as e:
            logger.error("RollbackManager: backup failed for %s: %s", path, e)
            return False

    def record_deleted(self, task_id: str, path: str) -> bool:
        """记录文件删除（自动备份被删除的文件）。

        返回 True 表示备份成功。
        """
        self._ensure_snapshot(task_id)

        if not os.path.exists(path):
            logger.warning("RollbackManager: cannot backup non-existent file: %s", path)
            return False

        try:
            fd, backup_path = tempfile.mkstemp(prefix="rollback_")
            os.close(fd)
            shutil.copy2(path, backup_path)

            self._snapshots[task_id].append(FileChange(
                change_type=ChangeType.DELETED,
                path=path,
                backup_path=backup_path,
            ))
            return True
        except Exception as e:
            logger.error("RollbackManager: backup failed for %s: %s", path, e)
            return False

    # ---- Rollback ----

    async def rollback(self, task_id: str) -> RollbackResult:
        """
        回滚所有变更到快照前状态。

        逆序执行（最后改的先回滚）。
        """
        changes = self._snapshots.pop(task_id, [])
        if not changes:
            return RollbackResult(success=True, changes_rolled_back=0)

        start = time.monotonic()
        rolled = 0
        failed = 0
        errors = []

        # 逆序回滚
        for change in reversed(changes):
            try:
                if change.change_type == ChangeType.CREATED:
                    # 删除创建的文件
                    if os.path.exists(change.path):
                        os.remove(change.path)
                        logger.debug("Rollback: removed %s", change.path)
                    rolled += 1

                elif change.change_type == ChangeType.MODIFIED:
                    # 恢复备份
                    if change.backup_path and os.path.exists(change.backup_path):
                        os.replace(change.backup_path, change.path)
                        logger.debug("Rollback: restored %s", change.path)
                        rolled += 1

                elif change.change_type == ChangeType.DELETED:
                    # 恢复被删除的文件
                    if change.backup_path and os.path.exists(change.backup_path):
                        os.makedirs(os.path.dirname(change.path), exist_ok=True)
                        os.replace(change.backup_path, change.path)
                        logger.debug("Rollback: restored deleted %s", change.path)
                        rolled += 1

            except Exception as e:
                failed += 1
                errors.append(f"{change.change_type.value} {change.path}: {e}")
                logger.error("Rollback failed for %s: %s", change.path, e)

        # 清理残留备份
        self._cleanup_backups(changes)

        result = RollbackResult(
            success=(failed == 0),
            changes_rolled_back=rolled,
            changes_failed=failed,
            errors=errors,
            duration_ms=(time.monotonic() - start) * 1000,
        )

        self._rollback_history.setdefault(task_id, []).append(result)
        return result

    async def commit(self, task_id: str) -> None:
        """提交变更（不回滚，清理备份）"""
        changes = self._snapshots.pop(task_id, [])
        self._cleanup_backups(changes)
        logger.debug("RollbackManager: committed %d changes for %s", len(changes), task_id)

    # ---- Info ----

    def get_pending_changes(self, task_id: str) -> list[dict]:
        """获取待回滚的变更列表"""
        changes = self._snapshots.get(task_id, [])
        return [
            {"type": c.change_type.value, "path": c.path, "timestamp": c.timestamp}
            for c in changes
        ]

    def get_history(self, task_id: str) -> list[dict]:
        """获取回滚历史"""
        results = self._rollback_history.get(task_id, [])
        return [
            {"success": r.success, "rolled_back": r.changes_rolled_back,
             "failed": r.changes_failed, "errors": r.errors,
             "duration_ms": r.duration_ms}
            for r in results
        ]

    def has_snapshot(self, task_id: str) -> bool:
        """是否有活跃快照"""
        return task_id in self._snapshots

    def clear(self, task_id: str) -> None:
        """强制清理快照"""
        changes = self._snapshots.pop(task_id, [])
        self._cleanup_backups(changes)

    # ---- Internal ----

    def _ensure_snapshot(self, task_id: str) -> None:
        if task_id not in self._snapshots:
            self._snapshots[task_id] = []

    def _cleanup_backups(self, changes: list[FileChange]) -> None:
        """清理临时备份文件"""
        for change in changes:
            if change.backup_path and os.path.exists(change.backup_path):
                try:
                    os.remove(change.backup_path)
                except OSError:
                    pass
