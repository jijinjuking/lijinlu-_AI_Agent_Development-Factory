"""
Worker Registry — Worker 注册表

管理所有 Worker 的注册、注销、状态查询。
"""

import time
import uuid
import logging
from typing import Dict, List, Optional

from .models import WorkerInfo, WorkerStatus

logger = logging.getLogger(__name__)


class WorkerRegistry:
    """Worker 注册表"""

    def __init__(self):
        self._workers: Dict[str, WorkerInfo] = {}

    def register(self, name: str, capabilities: List[str], host: str = "localhost",
                 port: int = 0, max_load: int = 5, metadata: dict = None) -> WorkerInfo:
        """注册 Worker"""
        worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        worker = WorkerInfo(
            worker_id=worker_id,
            name=name,
            status=WorkerStatus.ONLINE,
            capabilities=capabilities,
            max_load=max_load,
            host=host,
            port=port,
            metadata=metadata or {},
        )
        self._workers[worker_id] = worker
        logger.info(f"Worker registered: {worker_id} ({name})")
        return worker

    def deregister(self, worker_id: str) -> bool:
        """注销 Worker"""
        worker = self._workers.pop(worker_id, None)
        if worker:
            worker.status = WorkerStatus.OFFLINE
            logger.info(f"Worker deregistered: {worker_id}")
            return True
        return False

    def get(self, worker_id: str) -> Optional[WorkerInfo]:
        """获取 Worker"""
        return self._workers.get(worker_id)

    def list_all(self, status: WorkerStatus = None) -> List[WorkerInfo]:
        """列出所有 Worker"""
        workers = list(self._workers.values())
        if status:
            workers = [w for w in workers if w.status == status]
        return workers

    def list_by_capability(self, capability: str) -> List[WorkerInfo]:
        """按能力列出 Worker"""
        return [w for w in self._workers.values()
                if capability in w.capabilities and w.is_available]

    def list_by_capabilities(self, capabilities: List[str]) -> List[WorkerInfo]:
        """按多个能力列出 Worker（必须全部满足）"""
        result = []
        for w in self._workers.values():
            if w.is_available and all(c in w.capabilities for c in capabilities):
                result.append(w)
        return result

    def update_status(self, worker_id: str, status: WorkerStatus) -> bool:
        """更新状态"""
        worker = self._workers.get(worker_id)
        if worker:
            worker.status = status
            return True
        return False

    def update_load(self, worker_id: str, load: int) -> bool:
        """更新负载（限制在 [0, max_load] 区间）"""
        worker = self._workers.get(worker_id)
        if worker:
            worker.current_load = max(0, min(load, worker.max_load))
            return True
        return False

    def heartbeat(self, worker_id: str) -> bool:
        """更新心跳"""
        worker = self._workers.get(worker_id)
        if worker:
            worker.heartbeat_at = time.time()
            if worker.status == WorkerStatus.OFFLINE:
                worker.status = WorkerStatus.ONLINE
            return True
        return False

    def select_worker(self, capabilities: List[str] = None,
                      resource_req: dict = None) -> Optional[WorkerInfo]:
        """选择最佳 Worker（最少负载优先）"""
        if capabilities:
            candidates = self.list_by_capabilities(capabilities)
        else:
            candidates = [w for w in self._workers.values() if w.is_available]

        if not candidates:
            return None

        # 最少负载优先
        candidates.sort(key=lambda w: w.load_ratio)
        return candidates[0]

    @property
    def online_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.status == WorkerStatus.ONLINE)

    @property
    def total_load(self) -> int:
        return sum(w.current_load for w in self._workers.values())
