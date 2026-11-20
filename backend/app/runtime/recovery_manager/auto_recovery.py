"""
Auto Recovery — 自动恢复协调器

协调 FailureDetector + StateRollback，执行恢复计划。
这是专注于 FAILURE 恢复的协调器，区别于 W14 的 AutoRecovery（循环恢复）。
"""

import asyncio
import logging
import time
from typing import Optional

from .models import (
    FailureEvent, FailureType, RecoveryPlan, RecoveryResult,
    RecoveryAction, RecoveryStatus,
)
from .failure_detector import FailureDetector
from .state_rollback import StateRollback

logger = logging.getLogger(__name__)


class RecoveryOrchestrator:
    """
    故障恢复协调器。

    协调 FailureDetector + StateRollback，执行恢复计划。
    """

    def __init__(
        self,
        detector: FailureDetector,
        rollback: StateRollback,
        max_retries: int = 3,
    ):
        self.detector = detector
        self.rollback = rollback
        self.max_retries = max_retries
        self._active_plans: dict = {}

    async def handle_failure(self, failure: FailureEvent) -> RecoveryResult:
        """处理故障"""
        plan = self.detector.create_recovery_plan(failure)
        self._active_plans[failure.task_id] = plan
        return await self._execute_plan(plan)

    async def _execute_plan(self, plan: RecoveryPlan) -> RecoveryResult:
        """执行恢复计划"""
        start = time.time()
        actions_taken = []

        while plan.attempt < plan.max_attempts and plan.current_action:
            action = plan.current_action
            plan.status = RecoveryStatus.IN_PROGRESS

            try:
                if action == RecoveryAction.RETRY:
                    plan.attempt += 1
                    backoff = 2 ** (plan.attempt - 1)
                    await asyncio.sleep(backoff)
                    actions_taken.append(action)
                    # Retry success: task will resume externally
                    plan.status = RecoveryStatus.SUCCESS
                    self._active_plans.pop(plan.task_id, None)
                    return RecoveryResult(
                        task_id=plan.task_id,
                        success=True,
                        actions_taken=actions_taken,
                        duration_seconds=time.time() - start,
                    )

                elif action == RecoveryAction.ROLLBACK:
                    result = await self.rollback.rollback(
                        plan.task_id,
                        FailureEvent(
                            task_id=plan.task_id,
                            failure_type=plan.failure_type,
                            message="Rollback triggered",
                            checkpoint_seq_num=plan.checkpoint_seq_num,
                        ),
                    )
                    actions_taken.append(action)
                    if result.success:
                        plan.status = RecoveryStatus.SUCCESS
                        self._active_plans.pop(plan.task_id, None)
                        return RecoveryResult(
                            task_id=plan.task_id,
                            success=True,
                            actions_taken=actions_taken,
                            recovered_checkpoint=result.recovered_checkpoint,
                            duration_seconds=time.time() - start,
                        )
                    else:
                        plan.advance()
                        plan.attempt += 1

                elif action == RecoveryAction.FAILOVER:
                    plan.attempt += 1
                    await asyncio.sleep(1)
                    actions_taken.append(action)
                    plan.status = RecoveryStatus.SUCCESS
                    self._active_plans.pop(plan.task_id, None)
                    return RecoveryResult(
                        task_id=plan.task_id,
                        success=True,
                        actions_taken=actions_taken,
                        duration_seconds=time.time() - start,
                    )

                elif action == RecoveryAction.SKIP:
                    plan.advance()
                    actions_taken.append(action)
                    continue

                elif action == RecoveryAction.HUMAN_INTERVENTION:
                    plan.status = RecoveryStatus.FAILED
                    actions_taken.append(action)
                    self._active_plans.pop(plan.task_id, None)
                    return RecoveryResult(
                        task_id=plan.task_id,
                        success=False,
                        actions_taken=actions_taken,
                        failure_reason="All automated recovery failed, needs human intervention",
                        duration_seconds=time.time() - start,
                    )

            except Exception as e:
                logger.error(f"Recovery action {action} failed: {e}")
                plan.advance()

        # Exhausted all actions
        plan.status = RecoveryStatus.FAILED
        self._active_plans.pop(plan.task_id, None)
        return RecoveryResult(
            task_id=plan.task_id,
            success=False,
            actions_taken=actions_taken,
            failure_reason=f"Exhausted all recovery actions after {plan.attempt} attempts",
            duration_seconds=time.time() - start,
        )

    def get_active_plan(self, task_id: str) -> Optional[RecoveryPlan]:
        return self._active_plans.get(task_id)
