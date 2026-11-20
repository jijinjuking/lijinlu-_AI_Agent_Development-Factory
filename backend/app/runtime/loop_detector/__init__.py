"""
W14: 无限循环检测 + 自动恢复

组件:
- InfiniteLoopDetector: 三策略循环检测（单节点/序列重复/总迭代）
- AutoRecovery: 四策略自动恢复（替代路径/Checkpoint恢复/退避重试/人工介入）
"""

from app.runtime.loop_detector.models import (
    LoopAction,
    LoopDecision,
    LoopDetectionConfig,
    NodeVisitRecord,
    RecoveryAction,
    RecoveryResult,
    TaskLoopStats,
)
from app.runtime.loop_detector.loop_detector import (
    AutoRecovery,
    InfiniteLoopDetector,
)

__all__ = [
    # 核心类
    "InfiniteLoopDetector",
    "AutoRecovery",
    # 模型
    "LoopAction",
    "LoopDecision",
    "LoopDetectionConfig",
    "NodeVisitRecord",
    "RecoveryAction",
    "RecoveryResult",
    "TaskLoopStats",
]
