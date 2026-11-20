"""
Worker Manager — Data Models
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import time


class WorkerStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    DRAINING = "draining"
    UNHEALTHY = "unhealthy"


class ScalingDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    NONE = "none"


@dataclass
class WorkerInfo:
    """Worker 信息"""
    worker_id: str
    name: str
    status: WorkerStatus = WorkerStatus.OFFLINE
    capabilities: List[str] = field(default_factory=list)
    current_load: int = 0
    max_load: int = 5
    host: str = "localhost"
    port: int = 0
    heartbeat_at: float = field(default_factory=time.time)
    registered_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def load_ratio(self) -> float:
        if self.max_load == 0:
            return 1.0
        return self.current_load / self.max_load

    @property
    def is_available(self) -> bool:
        return self.status in (WorkerStatus.ONLINE,) and self.load_ratio < 1.0


@dataclass
class ScalingRule:
    """扩缩容规则"""
    metric: str  # "load_avg", "queue_depth", "error_rate"
    threshold_up: float
    threshold_down: float
    cooldown_seconds: float = 60.0
    max_workers: int = 10
    min_workers: int = 1
    scale_step: int = 1


@dataclass
class ScalingDecision:
    """扩缩容决策"""
    direction: ScalingDirection
    count: int
    reason: str
    timestamp: float = field(default_factory=time.time)
