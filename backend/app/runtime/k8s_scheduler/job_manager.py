"""
W25-26: K8s Job Scheduler — Job 管理器

管理 K8s Job 的完整生命周期：创建、监控、重试、清理。
支持并发 Job 数量限制和 Job 模板预定义。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from app.runtime.k8s_scheduler.k8s_client import AbstractK8sClient, LocalK8sClient
from app.runtime.k8s_scheduler.models import (
    K8sJobConfig,
    K8sJobRecord,
    K8sJobStatus,
    K8sJobType,
)

logger = logging.getLogger(__name__)


# ─── 预置 Job 模板 ───────────────────────────────────────────────────────────


PRESET_JOB_TEMPLATES: dict[str, K8sJobConfig] = {
    "langgraph_worker": K8sJobConfig(
        job_name="langgraph-worker-{task_id}",
        job_type=K8sJobType.LANGGRAPH_WORKER,
        image="ai-runtime-os/backend:latest",
        command=["python", "-m", "app.workers.langgraph_worker"],
        resource_requests={"memory": "1Gi", "cpu": "500m"},
        resource_limits={"memory": "4Gi", "cpu": "2000m"},
        active_deadline_seconds=7200,
        labels={"worker-type": "langgraph"},
    ),
    "sandbox_runner": K8sJobConfig(
        job_name="sandbox-runner-{task_id}",
        job_type=K8sJobType.SANDBOX_RUNNER,
        image="ai-runtime-os/sandbox:latest",
        command=["python", "-m", "app.workers.sandbox_worker"],
        resource_requests={"memory": "512Mi", "cpu": "500m"},
        resource_limits={"memory": "2Gi", "cpu": "1500m"},
        active_deadline_seconds=600,
        labels={"worker-type": "sandbox"},
    ),
    "checkpoint_worker": K8sJobConfig(
        job_name="checkpoint-worker-{task_id}",
        job_type=K8sJobType.CHECKPOINT_WORKER,
        image="ai-runtime-os/backend:latest",
        command=["python", "-m", "app.workers.checkpoint_worker"],
        resource_requests={"memory": "256Mi", "cpu": "100m"},
        resource_limits={"memory": "1Gi", "cpu": "500m"},
        active_deadline_seconds=300,
        labels={"worker-type": "checkpoint"},
    ),
    "batch_processor": K8sJobConfig(
        job_name="batch-processor-{task_id}",
        job_type=K8sJobType.BATCH_PROCESSOR,
        image="ai-runtime-os/backend:latest",
        command=["python", "-m", "app.workers.batch_worker"],
        resource_requests={"memory": "2Gi", "cpu": "1000m"},
        resource_limits={"memory": "8Gi", "cpu": "4000m"},
        active_deadline_seconds=14400,
        labels={"worker-type": "batch"},
    ),
}


# ─── K8sJobManager ───────────────────────────────────────────────────────────


class K8sJobManager:
    """K8s Job 生命周期管理器"""

    def __init__(
        self,
        k8s_client: AbstractK8sClient | None = None,
        max_concurrent_jobs: int = 50,
        job_timeout_seconds: int = 7200,
        monitor_interval_seconds: int = 5,
    ):
        self._client = k8s_client or LocalK8sClient()
        self._max_concurrent = max_concurrent_jobs
        self._job_timeout = job_timeout_seconds
        self._monitor_interval = monitor_interval_seconds
        self._active_jobs: dict[str, K8sJobRecord] = {}
        self._completed_jobs: dict[str, K8sJobRecord] = {}
        self._monitor_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._running = False
        self._subscribers: dict[str, list[asyncio.Event]] = {}

    # ── 公共 API ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """启动 Job 监控循环"""
        if self._running:
            return
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("K8sJobManager: monitoring started")

    async def stop(self) -> None:
        """停止 Job 监控"""
        self._running = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def submit_job(
        self,
        config: K8sJobConfig,
        task_id: str | None = None,
    ) -> K8sJobRecord:
        """提交一个 K8s Job"""
        async with self._lock:
            running_count = len(self._active_jobs)
            if running_count >= self._max_concurrent:
                raise RuntimeError(
                    f"Max concurrent jobs ({self._max_concurrent}) reached. "
                    f"Currently running: {running_count}"
                )

        record = await self._client.create_job(config)
        record.task_id = task_id

        async with self._lock:
            self._active_jobs[record.job_id] = record

        logger.info(
            f"K8sJobManager: submitted job {record.job_id} "
            f"(type={config.job_type.value}, task={task_id})"
        )
        return record

    async def submit_from_template(
        self,
        template_name: str,
        task_id: str,
        overrides: dict[str, Any] | None = None,
    ) -> K8sJobRecord:
        """使用预置模板提交 Job"""
        template = PRESET_JOB_TEMPLATES.get(template_name)
        if not template:
            available = ", ".join(PRESET_JOB_TEMPLATES.keys())
            raise ValueError(
                f"Unknown template '{template_name}'. Available: {available}"
            )

        # 深拷贝模板并应用覆盖
        config = K8sJobConfig(**{
            **template.__dict__,
            "job_name": template.job_name.replace("{task_id}", task_id[:8]),
        })
        if overrides:
            for key, value in overrides.items():
                if hasattr(config, key):
                    setattr(config, key, value)

        return await self.submit_job(config, task_id)

    async def get_job(self, job_id: str) -> K8sJobRecord | None:
        """获取 Job 记录"""
        async with self._lock:
            record = self._active_jobs.get(job_id) or self._completed_jobs.get(job_id)
        if record:
            # 刷新实时状态
            latest_status = await self._client.get_job_status(job_id)
            if latest_status != K8sJobStatus.UNKNOWN:
                record.status = latest_status
        return record

    async def cancel_job(self, job_id: str) -> bool:
        """取消 Job"""
        success = await self._client.cancel_job(job_id)
        if success:
            async with self._lock:
                record = self._active_jobs.pop(job_id, None)
                if record:
                    record.status = K8sJobStatus.CANCELLED
                    record.completed_at = datetime.now()
                    self._completed_jobs[job_id] = record
            self._notify_subscribers(job_id)
        return success

    async def delete_job(self, job_id: str) -> bool:
        """删除 Job（先取消如果活跃，再从记录中移除）"""
        async with self._lock:
            if job_id in self._active_jobs:
                # 先取消再移除
                pass  # handled below
            elif job_id in self._completed_jobs:
                del self._completed_jobs[job_id]
                await self._client.delete_job(job_id)
                return True
            else:
                return False

        # 活跃 job：取消 → 从 active 移除
        success = await self._client.cancel_job(job_id)
        if success:
            async with self._lock:
                self._active_jobs.pop(job_id, None)
            await self._client.delete_job(job_id)
            self._notify_subscribers(job_id)
        return success

    async def wait_for_job(self, job_id: str, timeout: float = 3600) -> K8sJobRecord:
        """等待 Job 完成（阻塞直到终态或超时）"""
        start = datetime.now()
        event = asyncio.Event()

        async with self._lock:
            if job_id not in self._subscribers:
                self._subscribers[job_id] = []
            self._subscribers[job_id].append(event)

        try:
            while True:
                elapsed = (datetime.now() - start).total_seconds()
                if elapsed > timeout:
                    raise asyncio.TimeoutError(
                        f"Job {job_id} did not complete within {timeout}s"
                    )

                record = await self.get_job(job_id)
                if record and record.status.is_terminal:
                    return record

                try:
                    await asyncio.wait_for(event.wait(), timeout=min(5, timeout - elapsed))
                except asyncio.TimeoutError:
                    continue
        finally:
            async with self._lock:
                if job_id in self._subscribers:
                    self._subscribers[job_id].remove(event)
                    if not self._subscribers[job_id]:
                        del self._subscribers[job_id]

    async def list_jobs(
        self, status_filter: str = "", namespace: str = ""
    ) -> list[K8sJobRecord]:
        """列出所有 Job"""
        async with self._lock:
            all_records = list(self._active_jobs.values()) + list(self._completed_jobs.values())
        if status_filter:
            all_records = [r for r in all_records if r.status.value == status_filter]
        if namespace:
            all_records = [r for r in all_records if r.k8s_namespace == namespace]
        return sorted(all_records, key=lambda r: r.created_at, reverse=True)

    async def get_stats(self) -> dict[str, int]:
        """获取 Job 统计"""
        async with self._lock:
            active = len(self._active_jobs)
            completed = len(self._completed_jobs)
            by_status: dict[str, int] = {}
            for r in list(self._active_jobs.values()) + list(self._completed_jobs.values()):
                key = r.status.value
                by_status[key] = by_status.get(key, 0) + 1
        return {
            "active": active,
            "completed": completed,
            "total": active + completed,
            "max_concurrent": self._max_concurrent,
            **by_status,
        }

    async def cleanup_old_jobs(self, max_age_hours: int = 24) -> int:
        """清理过期的已完成 Job"""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        removed = 0
        async with self._lock:
            stale = [
                jid for jid, r in self._completed_jobs.items()
                if r.completed_at and r.completed_at < cutoff
            ]
            for jid in stale:
                await self._client.delete_job(jid)
                del self._completed_jobs[jid]
                removed += 1
        logger.info(f"K8sJobManager: cleaned up {removed} old jobs (>{max_age_hours}h)")
        return removed

    def get_template_names(self) -> list[str]:
        """获取所有可用 Job 模板名称"""
        return list(PRESET_JOB_TEMPLATES.keys())

    def get_template(self, name: str) -> K8sJobConfig | None:
        """获取指定模板"""
        return PRESET_JOB_TEMPLATES.get(name)

    # ── 内部方法 ─────────────────────────────────────────────────────────

    def _notify_subscribers(self, job_id: str) -> None:
        """通知所有等待该 Job 的订阅者"""
        subscribers = self._subscribers.get(job_id, [])
        for event in subscribers:
            event.set()

    async def _monitor_loop(self) -> None:
        """后台监控循环 —— 定期检查活跃 Job 状态"""
        while self._running:
            try:
                await self._check_active_jobs()
            except Exception as exc:
                logger.error(f"K8sJobManager: monitor error: {exc}")

            try:
                await asyncio.sleep(self._monitor_interval)
            except asyncio.CancelledError:
                break

    async def _check_active_jobs(self) -> None:
        """检查所有活跃 Job 并更新状态"""
        async with self._lock:
            job_ids = list(self._active_jobs.keys())

        for job_id in job_ids:
            try:
                status = await self._client.get_job_status(job_id)
                async with self._lock:
                    record = self._active_jobs.get(job_id)
                    if not record:
                        continue
                    record.status = status

                if status.is_terminal:
                    async with self._lock:
                        if job_id in self._active_jobs:
                            record = self._active_jobs.pop(job_id)
                            self._completed_jobs[job_id] = record
                    self._notify_subscribers(job_id)

                # 超时检查
                if not status.is_terminal and record:
                    elapsed = (datetime.now() - record.created_at).total_seconds()
                    if elapsed > self._job_timeout:
                        logger.warning(
                            f"K8sJobManager: job {job_id} timed out after {elapsed}s"
                        )
                        await self.cancel_job(job_id)

            except Exception as exc:
                logger.warning(f"K8sJobManager: error checking job {job_id}: {exc}")
