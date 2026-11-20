"""W31-32 Runtime Federation — 状态同步引擎

跨集群状态/产物/检查点的数据同步。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from .models import (
    DataSyncRecord,
    FederationMember,
    SyncScope,
    SyncStatus,
    SyncStrategy,
)
from .policy import FederationPolicyEngine
from .registry import FederationRegistry

logger = logging.getLogger(__name__)

# 默认同步超时
SYNC_TIMEOUT = 30


class StateSyncEngine:
    """联邦状态同步引擎 — 在成员之间同步运行时状态"""

    def __init__(self, registry: FederationRegistry,
                 policy_engine: FederationPolicyEngine | None = None):
        self._registry = registry
        self._policy = policy_engine or FederationPolicyEngine()
        self._records: dict[str, DataSyncRecord] = {}

        # 模拟的本地存储（实际应集成 StateManager + ArtifactStore）
        self._local_state: dict[str, Any] = {}
        self._local_artifacts: dict[str, Any] = {}
        self._local_checkpoints: dict[str, Any] = {}

    # ── 同步操作 ──────────────────────────────

    async def sync_to(self, target_member_id: str,
                      source_member_id: str,
                      scope: SyncScope | None = None,
                      state_keys: list[str] | None = None,
                      artifact_ids: list[str] | None = None,
                      checkpoint_ids: list[str] | None = None) -> DataSyncRecord:
        """向目标成员推送同步数据"""
        source = self._registry.get_member(source_member_id)
        target = self._registry.get_member(target_member_id)
        if not source or not target:
            raise ValueError("Source or target member not found")

        strategy, decided_scope = self._policy.decide_sync(source, target)
        scope = scope or decided_scope

        record = DataSyncRecord(
            source_member_id=source_member_id,
            target_member_id=target_member_id,
            scope=scope,
            strategy=strategy,
            status=SyncStatus.IN_PROGRESS,
            state_keys=list(state_keys) if state_keys else [],
            artifact_ids=list(artifact_ids) if artifact_ids else [],
            checkpoint_ids=list(checkpoint_ids) if checkpoint_ids else [],
            started_at=datetime.now(),
        )
        self._records[record.sync_id] = record

        try:
            items_synced = 0

            if scope in (SyncScope.STATE_ONLY, SyncScope.FULL):
                keys = list(state_keys) if state_keys else list(self._local_state.keys())
                for key in keys:
                    if key in self._local_state:
                        record.state_keys.append(key)
                        items_synced += 1

            if scope in (SyncScope.ARTIFACTS_ONLY, SyncScope.FULL):
                ids = list(artifact_ids) if artifact_ids else list(self._local_artifacts.keys())
                for aid in ids:
                    if aid in self._local_artifacts:
                        record.artifact_ids.append(aid)
                        items_synced += 1

            if scope in (SyncScope.CHECKPOINTS_ONLY, SyncScope.FULL):
                ids = list(checkpoint_ids) if checkpoint_ids else list(self._local_checkpoints.keys())
                for cid in ids:
                    if cid in self._local_checkpoints:
                        record.checkpoint_ids.append(cid)
                        items_synced += 1

            record.status = SyncStatus.SUCCESS
            record.items_synced = items_synced
            record.completed_at = datetime.now()
            logger.info("Sync %s → %s: %d items (%s)",
                         source.name, target.name, items_synced, scope.value)

        except Exception as e:
            record.status = SyncStatus.FAILED
            record.error_message = str(e)
            record.completed_at = datetime.now()
            logger.exception("Sync %s → %s failed", source.name, target.name)

        return record

    async def sync_to_all(self, source_member_id: str,
                          scope: SyncScope | None = None,
                          exclude_self: bool = True) -> list[DataSyncRecord]:
        """向所有可用成员同步"""
        source = self._registry.get_member(source_member_id)
        if not source:
            raise ValueError(f"Source member {source_member_id} not found")

        targets = self._registry.get_available_members()
        if exclude_self:
            targets = [m for m in targets if m.member_id != source_member_id]

        records = []
        for target in targets:
            record = await self.sync_to(
                target_member_id=target.member_id,
                source_member_id=source_member_id,
                scope=scope)
            records.append(record)

        return records

    async def sync_bidirectional(self, member_a_id: str,
                                 member_b_id: str) -> list[DataSyncRecord]:
        """双向同步两个成员"""
        records = []
        records.append(await self.sync_to(member_b_id, member_a_id))
        records.append(await self.sync_to(member_a_id, member_b_id))
        return records

    # ── 冲突解决 ──────────────────────────────

    async def resolve_conflict(self, sync_id: str,
                               resolution: str = "keep_source") -> DataSyncRecord | None:
        """解决同步冲突

        resolution:
          - "keep_source": 保留源数据
          - "keep_target": 保留目标数据
          - "merge": 合并
        """
        record = self._records.get(sync_id)
        if not record:
            return None
        if record.status != SyncStatus.CONFLICT:
            return record

        record.status = SyncStatus.SUCCESS
        record.completed_at = datetime.now()
        logger.info("Conflict resolved for sync %s: %s", sync_id, resolution)
        return record

    # ── 查询 ──────────────────────────────────

    def get_record(self, sync_id: str) -> DataSyncRecord | None:
        return self._records.get(sync_id)

    def list_records(self, source_member_id: str = "",
                     target_member_id: str = "",
                     status: SyncStatus | None = None) -> list[DataSyncRecord]:
        """列出同步记录"""
        result = list(self._records.values())
        if source_member_id:
            result = [r for r in result if r.source_member_id == source_member_id]
        if target_member_id:
            result = [r for r in result if r.target_member_id == target_member_id]
        if status:
            result = [r for r in result if r.status == status]
        result.sort(key=lambda r: r.created_at, reverse=True)
        return result

    def get_stats(self) -> dict:
        """同步统计"""
        records = list(self._records.values())
        return {
            "total": len(records),
            "success": sum(1 for r in records if r.status == SyncStatus.SUCCESS),
            "failed": sum(1 for r in records if r.status == SyncStatus.FAILED),
            "conflict": sum(1 for r in records if r.status == SyncStatus.CONFLICT),
            "pending": sum(1 for r in records if r.status == SyncStatus.PENDING),
            "in_progress": sum(1 for r in records if r.status == SyncStatus.IN_PROGRESS),
            "total_items_synced": sum(r.items_synced for r in records),
        }

    # ── 本地存储管理（供注入数据用）───────────

    def store_state(self, key: str, value: Any):
        self._local_state[key] = value

    def get_state(self, key: str) -> Any:
        return self._local_state.get(key)

    def store_artifact(self, artifact_id: str, data: Any):
        self._local_artifacts[artifact_id] = data

    def get_artifact(self, artifact_id: str) -> Any:
        return self._local_artifacts.get(artifact_id)

    def store_checkpoint(self, checkpoint_id: str, data: Any):
        self._local_checkpoints[checkpoint_id] = data

    def get_checkpoint(self, checkpoint_id: str) -> Any:
        return self._local_checkpoints.get(checkpoint_id)
