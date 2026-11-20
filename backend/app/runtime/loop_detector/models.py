"""
W14: 无限循环检测 + 自动恢复 — 数据模型
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class LoopAction(str, Enum):
    """循环检测后的动作"""
    PAUSE = "pause_task"      # 暂停任务，等待人工检查
    ABORT = "abort_task"      # 终止任务
    SKIP = "skip_node"        # 跳过当前节点继续
    NOTIFY = "notify_admin"   # 通知管理员
    RETRY_MODEL = "retry_with_different_model"  # 换模型重试


class RecoveryAction(str, Enum):
    """自动恢复策略"""
    RESET_STATE = "reset_state"                      # 重置状态重新执行
    CONTINUE_FROM_CHECKPOINT = "continue_from_checkpoint"  # 从最近 checkpoint 恢复
    ALTERNATIVE_PATH = "alternative_path"            # 尝试替代路径
    HUMAN_INTERVENTION = "human_intervention"        # 转人工处理
    RETRY_WITH_BACKOFF = "retry_with_backoff"        # 指数退避重试


@dataclass
class LoopDetectionConfig:
    """循环检测配置"""
    max_node_visits: int = 30           # 单节点最大访问次数
    max_total_iterations: int = 100      # 总迭代次数上限
    sequence_window: int = 10            # 序列检测窗口大小
    min_cycle_length: int = 2            # 最小可检测循环长度
    max_cycle_length: int = 10           # 最大可检测循环长度
    enable_auto_recovery: bool = True    # 是否启用自动恢复
    recovery_max_retries: int = 3        # 恢复最大重试次数
    recovery_backoff_base: float = 2.0   # 退避基数（秒）


@dataclass
class LoopDecision:
    """循环检测决策"""
    is_loop: bool
    reason: str = ""
    action: LoopAction = LoopAction.PAUSE
    suggestion: str = ""
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RecoveryResult:
    """恢复操作结果"""
    success: bool
    action: RecoveryAction
    message: str = ""
    recovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class NodeVisitRecord:
    """节点访问记录"""
    task_id: str
    node_name: str
    visit_count: int = 1
    first_visit: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_visit: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TaskLoopStats:
    """任务循环统计信息"""
    task_id: str
    total_iterations: int = 0
    unique_nodes: int = 0
    top_nodes: list = field(default_factory=list)  # [(node_name, count), ...]
    loop_detected: bool = False
    last_detection: Optional[LoopDecision] = None
    recovery_count: int = 0
