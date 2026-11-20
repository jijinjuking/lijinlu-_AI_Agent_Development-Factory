"""
Recovery Manager — Data Models
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import time


class FailureType(str, Enum):
    """故障类型"""
    TIMEOUT = "timeout"
    CRASH = "crash"
    OOM = "oom"
    NETWORK = "network"
    SANDBOX_FAILURE = "sandbox_failure"
    UNKNOWN = "unknown"


class RecoveryAction(str, Enum):
    """恢复动作"""
    RETRY = "retry"
    ROLLBACK = "rollback"
    FAILOVER = "failover"
    SKIP = "skip"
    HUMAN_INTERVENTION = "human_intervention"


class RecoveryStatus(str, Enum):
    """恢复状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class FailureEvent:
    """故障事件"""
    task_id: str
    failure_type: FailureType
    message: str
    node_id: Optional[str] = None
    checkpoint_seq_num: int = 0
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryPlan:
    """恢复计划"""
    task_id: str
    failure_type: FailureType
    actions: List[RecoveryAction]
    checkpoint_seq_num: int = 0
    current_action_index: int = 0
    status: RecoveryStatus = RecoveryStatus.PENDING
    attempt: int = 0
    max_attempts: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def current_action(self) -> Optional[RecoveryAction]:
        if self.current_action_index < len(self.actions):
            return self.actions[self.current_action_index]
        return None

    def advance(self) -> Optional[RecoveryAction]:
        self.current_action_index += 1
        return self.current_action


@dataclass
class RecoveryResult:
    """恢复结果"""
    task_id: str
    success: bool
    actions_taken: List[RecoveryAction] = field(default_factory=list)
    failure_reason: Optional[str] = None
    recovered_checkpoint: Optional[int] = None
    duration_seconds: float = 0.0
