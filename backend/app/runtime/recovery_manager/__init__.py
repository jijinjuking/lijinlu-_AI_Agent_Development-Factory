"""
AI Runtime OS — Recovery Manager

组件:
- FailureDetector: 故障检测（心跳/崩溃/OOM/网络/沙箱）
- StateRollback: 状态回滚（全量/部分/Event Replay）
- RecoveryOrchestrator: 恢复协调器
"""

from .models import (
    FailureType, RecoveryAction, RecoveryStatus,
    FailureEvent, RecoveryPlan, RecoveryResult,
)
from .failure_detector import FailureDetector, DetectorConfig
from .state_rollback import StateRollback
from .auto_recovery import RecoveryOrchestrator

__all__ = [
    "FailureType",
    "RecoveryAction",
    "RecoveryStatus",
    "FailureEvent",
    "RecoveryPlan",
    "RecoveryResult",
    "FailureDetector",
    "DetectorConfig",
    "StateRollback",
    "RecoveryOrchestrator",
]
