"""
State Rollback — 状态回滚器

从 Checkpoint 恢复 State，支持部分回滚和全量回滚。
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from .models import FailureEvent, RecoveryResult, RecoveryAction, RecoveryStatus

logger = logging.getLogger(__name__)


class StateRollback:
    """
    状态回滚器。

    策略:
    - full_rollback: 回到最近 checkpoint 的完整 snapshot
    - partial_rollback: 仅回滚指定字段
    - replay: 从 checkpoint 重放到故障点前
    """

    def __init__(self, checkpoint_manager, state_manager):
        self.checkpoint_mgr = checkpoint_manager
        self.state_mgr = state_manager
        self._rollback_history: Dict[str, list] = {}

    async def rollback(
        self, task_id: str, failure: FailureEvent, method: str = "full"
    ) -> RecoveryResult:
        """
        执行状态回滚。

        返回 RecoveryResult。
        """
        start = time.time()

        try:
            if method == "full":
                checkpoint = await self.checkpoint_mgr.load_latest(task_id)
                if not checkpoint:
                    return RecoveryResult(
                        task_id=task_id,
                        success=False,
                        failure_reason="No checkpoint available",
                    )

                await self.state_mgr.save(task_id, checkpoint.state_snapshot)
                recovered_seq = checkpoint.event_seq_num

            elif method == "partial":
                checkpoint = await self.checkpoint_mgr.load_latest(task_id)
                if not checkpoint:
                    return RecoveryResult(
                        task_id=task_id,
                        success=False,
                        failure_reason="No checkpoint available",
                    )
                # Merge: keep current messages, restore control state
                current = await self.state_mgr.load(task_id) or {}
                snapshot = checkpoint.state_snapshot or {}
                merged = {
                    **snapshot,
                    "messages": current.get("messages", snapshot.get("messages", [])),
                    "artifact_refs": current.get("artifact_refs", snapshot.get("artifact_refs", [])),
                    "phase": current.get("phase", snapshot.get("phase", "created")),
                }
                await self.state_mgr.save(task_id, merged)
                recovered_seq = checkpoint.event_seq_num

            elif method == "replay":
                events = await self._replay_events(task_id, failure.checkpoint_seq_num)
                state = await self.state_mgr.load(task_id) or {}
                for event in events:
                    if event.get("timestamp", 0) >= failure.timestamp:
                        break
                    state = self._apply_event(state, event)
                await self.state_mgr.save(task_id, state)
                recovered_seq = failure.checkpoint_seq_num

            else:
                return RecoveryResult(
                    task_id=task_id,
                    success=False,
                    failure_reason=f"Unknown rollback method: {method}",
                )

            self._record_rollback(task_id, method, True)
            return RecoveryResult(
                task_id=task_id,
                success=True,
                actions_taken=[RecoveryAction.ROLLBACK],
                recovered_checkpoint=recovered_seq,
                duration_seconds=time.time() - start,
            )

        except Exception as e:
            logger.error(f"Rollback failed for {task_id}: {e}")
            self._record_rollback(task_id, method, False)
            return RecoveryResult(
                task_id=task_id,
                success=False,
                failure_reason=str(e),
                duration_seconds=time.time() - start,
            )

    async def _replay_events(self, task_id: str, after_seq: int) -> List[dict]:
        """Replay events after checkpoint"""
        # Placeholder: returns empty list (needs EventBus integration)
        return []

    def _apply_event(self, state: dict, event: dict) -> dict:
        """Apply event to state"""
        event_type = event.get("type", "")
        payload = event.get("payload", {})

        if event_type == "artifact_created":
            state.setdefault("artifact_refs", []).append(payload.get("artifact_id", ""))
        elif event_type == "message_added":
            state.setdefault("messages", []).append(payload.get("message", ""))
        elif event_type == "phase_changed":
            state["phase"] = payload.get("phase", state.get("phase"))

        return state

    def _record_rollback(self, task_id: str, method: str, success: bool) -> None:
        self._rollback_history.setdefault(task_id, []).append({
            "method": method,
            "success": success,
            "timestamp": time.time(),
        })

    def get_rollback_history(self, task_id: str) -> List[dict]:
        return self._rollback_history.get(task_id, [])
