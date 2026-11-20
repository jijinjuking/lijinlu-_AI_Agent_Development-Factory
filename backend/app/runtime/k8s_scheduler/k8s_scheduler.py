"""
W25-26: K8s Job Scheduler — K8s 调度器

桥接现有 Runtime 系统和 K8s Job 系统。
将 Scheduler 中的任务分发到 K8s 集群执行，收集结果回传。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from app.runtime.k8s_scheduler.job_manager import K8sJobManager
from app.runtime.k8s_scheduler.k8s_client import (
    AbstractK8sClient,
    K8sClientFactory,
)
from app.runtime.k8s_scheduler.models import (
    K8sClusterInfo,
    K8sJobConfig,
    K8sJobRecord,
    K8sJobStatus,
    K8sJobType,
    K8sNodeInfo,
)

logger = logging.getLogger(__name__)


class K8sScheduler:
    """K8s 调度器 —— 将 Runtime 任务映射为 K8s Job"""

    def __init__(
        self,
        job_manager: K8sJobManager | None = None,
        k8s_client: AbstractK8sClient | None = None,
        default_namespace: str = "ai-runtime-os",
    ):
        self._client = k8s_client
        self._job_manager = job_manager
        self._namespace = default_namespace
        self._initialized = False

    async def initialize(self) -> None:
        """初始化 K8s 连接和 Job 管理器"""
        if self._initialized:
            return

        if self._client is None:
            self._client = await K8sClientFactory.get_client()

        if self._job_manager is None:
            self._job_manager = K8sJobManager(k8s_client=self._client)

        await self._job_manager.start()
        self._initialized = True
        logger.info("K8sScheduler: initialized")

    async def shutdown(self) -> None:
        """关闭 K8s 调度器"""
        if self._job_manager:
            await self._job_manager.stop()
        self._initialized = False

    # ── Job 操作 ──────────────────────────────────────────────────────────

    async def submit_task_as_job(
        self,
        task_id: str,
        capability: str = "",
        workflow_payload: dict[str, Any] | None = None,
        template_name: str = "langgraph_worker",
        extra_env: dict[str, str] | None = None,
    ) -> K8sJobRecord:
        """将 Runtime 任务提交为 K8s Job"""
        if not self._initialized:
            await self.initialize()

        # 选模板
        template_map = {
            "langgraph": "langgraph_worker",
            "sandbox": "sandbox_runner",
            "checkpoint": "checkpoint_worker",
            "batch": "batch_processor",
        }
        tmpl_name = template_map.get(capability, template_name)

        overrides: dict[str, Any] = {}
        if extra_env:
            overrides["env_vars"] = extra_env

        record = await self._job_manager.submit_from_template(
            template_name=tmpl_name,
            task_id=task_id,
            overrides=overrides if overrides else None,
        )

        logger.info(
            f"K8sScheduler: dispatched task {task_id} -> "
            f"K8s job {record.job_id} (template={tmpl_name})"
        )
        return record

    async def submit_custom_job(
        self,
        config: K8sJobConfig,
        task_id: str | None = None,
    ) -> K8sJobRecord:
        """提交自定义配置的 K8s Job"""
        if not self._initialized:
            await self.initialize()
        return await self._job_manager.submit_job(config, task_id)

    async def get_job_result(
        self, job_id: str, wait: bool = False, timeout: float = 3600
    ) -> K8sJobRecord | None:
        """获取 Job 结果（可选等待完成）"""
        if not self._initialized:
            await self.initialize()

        if wait:
            return await self._job_manager.wait_for_job(job_id, timeout)

        return await self._job_manager.get_job(job_id)

    async def cancel_task_job(self, task_id: str) -> bool:
        """取消与 Runtime 任务关联的 K8s Job"""
        if not self._initialized:
            await self.initialize()

        jobs = await self._job_manager.list_jobs()
        for job in jobs:
            if job.task_id == task_id and not job.status.is_terminal:
                return await self._job_manager.cancel_job(job.job_id)
        return False

    async def delete_job(self, job_id: str) -> bool:
        """删除 K8s Job"""
        if not self._initialized:
            await self.initialize()
        return await self._job_manager.delete_job(job_id)

    async def batch_submit(
        self,
        tasks: list[dict[str, Any]],
        template_name: str = "langgraph_worker",
        max_concurrent: int = 10,
    ) -> list[K8sJobRecord]:
        """批量提交任务为 K8s Job（带并发控制）"""
        if not self._initialized:
            await self.initialize()

        semaphore = asyncio.Semaphore(max_concurrent)
        records: list[K8sJobRecord] = []

        async def _submit_one(task: dict) -> None:
            async with semaphore:
                record = await self.submit_task_as_job(
                    task_id=task["task_id"],
                    capability=task.get("capability", ""),
                    template_name=template_name,
                    extra_env=task.get("env_vars"),
                )
                records.append(record)

        tasks_coros = [_submit_one(t) for t in tasks]
        await asyncio.gather(*tasks_coros, return_exceptions=True)
        return records

    # ── 集群操作 ──────────────────────────────────────────────────────────

    async def get_cluster_info(self) -> K8sClusterInfo:
        """获取 K8s 集群信息"""
        if not self._initialized:
            await self.initialize()
        return await self._client.get_cluster_info()

    async def get_nodes(self) -> list[K8sNodeInfo]:
        """获取集群节点列表"""
        if not self._initialized:
            await self.initialize()
        return await self._client.list_nodes()

    async def get_job_stats(self) -> dict[str, int]:
        """获取 Job 统计"""
        if not self._initialized:
            await self.initialize()
        return await self._job_manager.get_stats()

    async def list_all_jobs(self, status_filter: str = "") -> list[dict[str, Any]]:
        """列出所有 K8s Job"""
        if not self._initialized:
            await self.initialize()
        records = await self._job_manager.list_jobs(status_filter=status_filter)
        return [r.to_dict() for r in records]

    async def get_job_logs(self, job_id: str, tail_lines: int = 100) -> str:
        """获取 Job 日志"""
        if not self._initialized:
            await self.initialize()
        return await self._client.get_job_logs(job_id, tail_lines)

    async def cleanup_jobs(self, max_age_hours: int = 24) -> int:
        """清理过期 Job"""
        if not self._initialized:
            await self.initialize()
        return await self._job_manager.cleanup_old_jobs(max_age_hours)

    def get_templates(self) -> list[dict[str, Any]]:
        """获取所有 Job 模板"""
        templates = []
        for name in self._job_manager.get_template_names() if self._job_manager else []:
            tmpl = self._job_manager.get_template(name) if self._job_manager else None
            if tmpl:
                templates.append({
                    "name": name,
                    "config": tmpl.to_dict(),
                })
        return templates
