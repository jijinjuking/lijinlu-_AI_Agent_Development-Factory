"""
Failure Detector — 故障检测器

检测策略:
- 心跳超时
- 异常信号捕获
- 资源耗尽检测
"""

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field

from .models import FailureEvent, FailureType, RecoveryPlan, RecoveryAction

logger = logging.getLogger(__name__)


@dataclass
class DetectorConfig:
    """故障检测配置"""
    heartbeat_timeout_seconds: float = 30.0
    max_consecutive_failures: int = 3
    oom_memory_threshold_mb: int = 2048
    check_interval_seconds: float = 5.0


@dataclass
class TaskHeartbeat:
    """任务心跳"""
    task_id: str
    last_beat: float
    consecutive_misses: int = 0


class FailureDetector:
    """
    故障检测器。

    监控任务心跳、异常信号、资源耗尽，生成 FailureEvent。
    """

    def __init__(self, config: Optional[DetectorConfig] = None):
        self.config = config or DetectorConfig()
        self._heartbeats: Dict[str, TaskHeartbeat] = {}
        self._failure_history: Dict[str, List[FailureEvent]] = {}
        self._handlers: Dict[FailureType, List[Callable]] = {}

    # ---- Heartbeat ----

    def heartbeat(self, task_id: str) -> None:
        """注册心跳"""
        self._heartbeats[task_id] = TaskHeartbeat(
            task_id=task_id,
            last_beat=time.time(),
            consecutive_misses=0,
        )

    def check_heartbeat(self, task_id: str) -> Optional[FailureEvent]:
        """检查心跳超时（同步方法，无 I/O 操作）"""
        hb = self._heartbeats.get(task_id)
        if not hb:
            return None

        elapsed = time.time() - hb.last_beat
        if elapsed > self.config.heartbeat_timeout_seconds:
            hb.consecutive_misses += 1
            if hb.consecutive_misses >= self.config.max_consecutive_failures:
                return self._create_failure(task_id, FailureType.TIMEOUT,
                    f"Task heartbeat timeout after {elapsed:.1f}s")

        return None

    # ---- Detection ----

    def detect_crash(self, task_id: str, exception: Exception) -> FailureEvent:
        """检测崩溃"""
        return self._create_failure(task_id, FailureType.CRASH, str(exception))

    def detect_oom(self, task_id: str, memory_mb: int) -> Optional[FailureEvent]:
        """检测内存溢出"""
        if memory_mb > self.config.oom_memory_threshold_mb:
            return self._create_failure(task_id, FailureType.OOM,
                f"Memory exceeded: {memory_mb}MB > {self.config.oom_memory_threshold_mb}MB")
        return None

    def detect_sandbox_failure(self, task_id: str, error: str) -> FailureEvent:
        """检测沙箱故障"""
        return self._create_failure(task_id, FailureType.SANDBOX_FAILURE, error)

    def detect_network_failure(self, task_id: str, error: str) -> FailureEvent:
        """检测网络故障"""
        return self._create_failure(task_id, FailureType.NETWORK, error)

    # ---- Plan Generation ----

    def create_recovery_plan(self, failure: FailureEvent) -> RecoveryPlan:
        """根据故障类型生成恢复计划"""
        actions = self._get_recovery_actions(failure.failure_type)
        return RecoveryPlan(
            task_id=failure.task_id,
            failure_type=failure.failure_type,
            actions=actions,
            checkpoint_seq_num=failure.checkpoint_seq_num,
            metadata={"failure_message": failure.message},
        )

    def _get_recovery_actions(self, failure_type: FailureType) -> List[RecoveryAction]:
        """根据故障类型返回恢复动作序列"""
        mapping = {
            FailureType.TIMEOUT: [
                RecoveryAction.RETRY,
                RecoveryAction.ROLLBACK,
                RecoveryAction.HUMAN_INTERVENTION,
            ],
            FailureType.CRASH: [
                RecoveryAction.ROLLBACK,
                RecoveryAction.RETRY,
                RecoveryAction.HUMAN_INTERVENTION,
            ],
            FailureType.OOM: [
                RecoveryAction.RETRY,
                RecoveryAction.HUMAN_INTERVENTION,
            ],
            FailureType.NETWORK: [
                RecoveryAction.RETRY,
                RecoveryAction.FAILOVER,
                RecoveryAction.HUMAN_INTERVENTION,
            ],
            FailureType.SANDBOX_FAILURE: [
                RecoveryAction.RETRY,
                RecoveryAction.FAILOVER,
                RecoveryAction.HUMAN_INTERVENTION,
            ],
            FailureType.UNKNOWN: [
                RecoveryAction.RETRY,
                RecoveryAction.ROLLBACK,
                RecoveryAction.HUMAN_INTERVENTION,
            ],
        }
        return mapping.get(failure_type, mapping[FailureType.UNKNOWN])

    # ---- Handler Registration ----

    def on_failure(self, failure_type: FailureType, handler: Callable) -> None:
        """注册故障处理器"""
        self._handlers.setdefault(failure_type, []).append(handler)

    async def handle_failure(self, failure: FailureEvent) -> None:
        """触发故障处理器"""
        handlers = self._handlers.get(failure.failure_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(failure)
                else:
                    handler(failure)
            except Exception as e:
                logger.error(f"Handler failed for {failure.failure_type}: {e}")

    # ---- History ----

    def get_history(self, task_id: str) -> List[FailureEvent]:
        """获取故障历史"""
        return self._failure_history.get(task_id, [])

    def clear_history(self, task_id: str) -> None:
        """清除故障历史"""
        self._failure_history.pop(task_id, None)
        self._heartbeats.pop(task_id, None)

    # ---- Internal ----

    def _create_failure(self, task_id: str, ftype: FailureType, msg: str) -> FailureEvent:
        event = FailureEvent(task_id=task_id, failure_type=ftype, message=msg)
        self._failure_history.setdefault(task_id, []).append(event)
        return event
