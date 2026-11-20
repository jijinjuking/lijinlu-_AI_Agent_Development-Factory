"""
W25-26: K8s Job Scheduler — K8s 客户端封装

支持两种模式:
- RealK8sClient: 真实 Kubernetes API 调用（需要 kubernetes 包 + kubeconfig）
- LocalK8sClient: 本地模拟执行（subprocess），开发/测试环境使用

通过 K8sClientFactory 自动选择合适的客户端。
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from app.runtime.k8s_scheduler.models import (
    K8sClusterInfo,
    K8sDeploymentSpec,
    K8sJobConfig,
    K8sJobRecord,
    K8sJobStatus,
    K8sNodeInfo,
)

logger = logging.getLogger(__name__)


# ─── 抽象基类 ────────────────────────────────────────────────────────────────


class AbstractK8sClient(ABC):
    """K8s 客户端抽象接口"""

    @abstractmethod
    async def create_job(self, config: K8sJobConfig) -> K8sJobRecord:
        """创建并启动一个 K8s Job"""
        ...

    @abstractmethod
    async def get_job_status(self, job_id: str) -> K8sJobStatus:
        """获取 Job 当前状态"""
        ...

    @abstractmethod
    async def get_job_logs(self, job_id: str, tail_lines: int = 100) -> str:
        """获取 Job 日志"""
        ...

    @abstractmethod
    async def cancel_job(self, job_id: str) -> bool:
        """取消 Job"""
        ...

    @abstractmethod
    async def delete_job(self, job_id: str) -> bool:
        """删除 Job 及关联资源"""
        ...

    @abstractmethod
    async def list_jobs(self, namespace: str = "", status_filter: str = "") -> list[K8sJobRecord]:
        """列出所有 Job"""
        ...

    @abstractmethod
    async def list_nodes(self) -> list[K8sNodeInfo]:
        """列出集群节点"""
        ...

    @abstractmethod
    async def get_cluster_info(self) -> K8sClusterInfo:
        """获取集群概览"""
        ...

    @abstractmethod
    async def apply_deployment(self, spec: K8sDeploymentSpec) -> bool:
        """应用 Deployment 到集群"""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """检查 K8s 集群是否可用"""
        ...


# ─── 本地模拟客户端 ──────────────────────────────────────────────────────────


class LocalK8sClient(AbstractK8sClient):
    """本地开发模式 —— 用 subprocess 模拟 K8s Job 执行"""

    def __init__(self, work_dir: str = ""):
        self._work_dir = work_dir or str(Path(tempfile.gettempdir()) / "k8s-local")
        self._jobs: dict[str, K8sJobRecord] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._job_logs: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()
        Path(self._work_dir).mkdir(parents=True, exist_ok=True)

    async def create_job(self, config: K8sJobConfig) -> K8sJobRecord:
        record = K8sJobRecord(
            job_config=config,
            k8s_job_name=config.job_name,
            k8s_namespace=config.namespace,
            status=K8sJobStatus.CREATED,
        )

        async with self._lock:
            self._jobs[record.job_id] = record
            self._job_logs[record.job_id] = []

        # 异步启动本地进程
        asyncio.create_task(self._run_local_job(record))
        return record

    async def _run_local_job(self, record: K8sJobRecord) -> None:
        """用 subprocess 在本地执行 Job"""
        config = record.job_config
        cmd = config.command if config.command else ["echo", "K8s Local Job: no command specified"]

        # 注入环境变量
        env = {**__import__("os").environ, **config.env_vars}
        env["K8S_JOB_ID"] = record.job_id
        env["K8S_JOB_NAME"] = config.job_name

        record.status = K8sJobStatus.PENDING
        record.started_at = datetime.now()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self._work_dir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async with self._lock:
                self._processes[record.job_id] = proc

            record.status = K8sJobStatus.RUNNING
            record.pod_name = f"local-{record.job_id[:8]}"
            record.node_name = "local-dev"

            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(),
                timeout=config.active_deadline_seconds,
            )

            stdout_text = stdout_data.decode("utf-8", errors="replace") if stdout_data else ""
            stderr_text = stderr_data.decode("utf-8", errors="replace") if stderr_data else ""

            async with self._lock:
                self._job_logs[record.job_id].extend(stdout_text.splitlines())

            record.exit_code = proc.returncode

            if proc.returncode == 0:
                record.status = K8sJobStatus.SUCCEEDED
                try:
                    record.result_data = json.loads(stdout_text.strip().split("\n")[-1])
                except (json.JSONDecodeError, IndexError):
                    record.result_data = {"output": stdout_text[:1000]}
            else:
                record.status = K8sJobStatus.FAILED
                record.error_message = stderr_text[:2000] or f"Exit code: {proc.returncode}"

        except asyncio.TimeoutError:
            record.status = K8sJobStatus.TIMED_OUT
            record.error_message = f"Job exceeded deadline of {config.active_deadline_seconds}s"
            async with self._lock:
                if record.job_id in self._processes:
                    self._processes[record.job_id].kill()
        except Exception as exc:
            record.status = K8sJobStatus.FAILED
            record.error_message = str(exc)[:2000]
        finally:
            record.completed_at = datetime.now()
            async with self._lock:
                self._processes.pop(record.job_id, None)

    async def get_job_status(self, job_id: str) -> K8sJobStatus:
        async with self._lock:
            record = self._jobs.get(job_id)
        return record.status if record else K8sJobStatus.UNKNOWN

    async def get_job_logs(self, job_id: str, tail_lines: int = 100) -> str:
        async with self._lock:
            logs = self._job_logs.get(job_id, [])
        return "\n".join(logs[-tail_lines:])

    async def cancel_job(self, job_id: str) -> bool:
        async with self._lock:
            proc = self._processes.pop(job_id, None)
            record = self._jobs.get(job_id)
        if proc and proc.returncode is None:
            proc.kill()
        if record:
            record.status = K8sJobStatus.CANCELLED
            record.completed_at = datetime.now()
            return True
        return False

    async def delete_job(self, job_id: str) -> bool:
        await self.cancel_job(job_id)
        async with self._lock:
            self._jobs.pop(job_id, None)
            self._job_logs.pop(job_id, None)
        return True

    async def list_jobs(self, namespace: str = "", status_filter: str = "") -> list[K8sJobRecord]:
        async with self._lock:
            records = list(self._jobs.values())
        if namespace:
            records = [r for r in records if r.k8s_namespace == namespace]
        if status_filter:
            records = [r for r in records if r.status.value == status_filter]
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    async def list_nodes(self) -> list[K8sNodeInfo]:
        return [
            K8sNodeInfo(
                node_name="local-dev",
                node_ip="127.0.0.1",
                status="Ready",
                capacity_cpu="8",
                capacity_memory="16Gi",
                allocatable_cpu="7",
                allocatable_memory="14Gi",
                pod_count=len(self._jobs),
                os_image="Windows/Local",
                architecture="amd64",
            )
        ]

    async def get_cluster_info(self) -> K8sClusterInfo:
        nodes = await self.list_nodes()
        return K8sClusterInfo(
            cluster_name="local-dev",
            api_server_version="simulated",
            node_count=len(nodes),
            ready_nodes=sum(1 for n in nodes if n.is_ready),
            pod_count=len(self._jobs),
            job_count=len([r for r in self._jobs.values()
                          if r.status == K8sJobStatus.RUNNING]),
            nodes=nodes,
        )

    async def apply_deployment(self, spec: K8sDeploymentSpec) -> bool:
        logger.info(f"LocalK8s: apply_deployment(spec) = simulated (name={spec.name}, replicas={spec.replicas})")
        return True

    async def is_available(self) -> bool:
        return True  # 本地模式始终可用


# ─── 真实 K8s 客户端 ─────────────────────────────────────────────────────────


class RealK8sClient(AbstractK8sClient):
    """真实 Kubernetes API 客户端（需要 kubernetes 包 + kubeconfig）"""

    def __init__(self, namespace: str = "ai-runtime-os"):
        self._namespace = namespace
        self._jobs: dict[str, K8sJobRecord] = {}
        self._batch_api = None
        self._core_api = None
        self._apps_api = None
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        try:
            from kubernetes import client, config as kube_config
            kube_config.load_config()
            self._batch_api = client.BatchV1Api()
            self._core_api = client.CoreV1Api()
            self._apps_api = client.AppsV1Api()
            self._initialized = True
            logger.info("RealK8sClient: connected to Kubernetes cluster")
        except Exception as exc:
            logger.warning(f"RealK8sClient: failed to initialize: {exc}")
            raise

    async def create_job(self, config: K8sJobConfig) -> K8sJobRecord:
        await self._ensure_initialized()
        from kubernetes import client

        job = client.V1Job(
            metadata=client.V1ObjectMeta(
                name=config.job_name,
                namespace=config.namespace or self._namespace,
                labels={"app": "ai-runtime-os", "job-type": config.job_type.value, **config.labels},
                annotations=config.annotations,
            ),
            spec=client.V1JobSpec(
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(labels={"job-name": config.job_name}),
                    spec=client.V1PodSpec(
                        containers=[client.V1Container(
                            name=config.job_name,
                            image=config.image,
                            command=config.command or None,
                            args=config.args or None,
                            env=[client.V1EnvVar(name=k, value=v) for k, v in config.env_vars.items()],
                            resources=client.V1ResourceRequirements(
                                requests=config.resource_requests,
                                limits=config.resource_limits,
                            ),
                            volume_mounts=[
                                client.V1VolumeMount(**vm) for vm in config.volume_mounts
                            ] if config.volume_mounts else None,
                        )],
                        restart_policy=config.restart_policy,
                        node_selector=config.node_selector or None,
                        tolerations=[
                            client.V1Toleration(**t) for t in config.tolerations
                        ] if config.tolerations else None,
                        volumes=[client.V1Volume(**v) for v in config.volumes] if config.volumes else None,
                        service_account_name=config.service_account or None,
                    ),
                ),
                backoff_limit=config.backoff_limit,
                active_deadline_seconds=config.active_deadline_seconds,
                ttl_seconds_after_finished=config.ttl_seconds_after_finished,
            ),
        )

        ns = config.namespace or self._namespace
        created = self._batch_api.create_namespaced_job(namespace=ns, body=job)

        record = K8sJobRecord(
            job_config=config,
            k8s_job_name=config.job_name,
            k8s_namespace=ns,
            status=K8sJobStatus.CREATED,
        )
        self._jobs[record.job_id] = record
        return record

    async def get_job_status(self, job_id: str) -> K8sJobStatus:
        await self._ensure_initialized()
        record = self._jobs.get(job_id)
        if not record:
            return K8sJobStatus.UNKNOWN
        try:
            k8s_job = self._batch_api.read_namespaced_job(
                name=record.k8s_job_name, namespace=record.k8s_namespace
            )
            return self._map_k8s_status(k8s_job)
        except Exception:
            return K8sJobStatus.UNKNOWN

    async def get_job_logs(self, job_id: str, tail_lines: int = 100) -> str:
        await self._ensure_initialized()
        record = self._jobs.get(job_id)
        if not record:
            return ""
        try:
            pods = self._core_api.list_namespaced_pod(
                namespace=record.k8s_namespace,
                label_selector=f"job-name={record.k8s_job_name}",
            )
            if not pods.items:
                return ""
            pod_name = pods.items[0].metadata.name
            return self._core_api.read_namespaced_pod_log(
                name=pod_name, namespace=record.k8s_namespace, tail_lines=tail_lines
            )
        except Exception as exc:
            logger.warning(f"Failed to get logs for job {job_id}: {exc}")
            return ""

    async def cancel_job(self, job_id: str) -> bool:
        await self._ensure_initialized()
        record = self._jobs.get(job_id)
        if not record:
            return False
        try:
            self._batch_api.delete_namespaced_job(
                name=record.k8s_job_name, namespace=record.k8s_namespace,
                propagation_policy="Foreground",
            )
            record.status = K8sJobStatus.CANCELLED
            return True
        except Exception as exc:
            logger.warning(f"Failed to cancel job {job_id}: {exc}")
            return False

    async def delete_job(self, job_id: str) -> bool:
        await self._ensure_initialized()
        record = self._jobs.get(job_id)
        if not record:
            return False
        try:
            self._batch_api.delete_namespaced_job(
                name=record.k8s_job_name, namespace=record.k8s_namespace,
            )
            self._jobs.pop(job_id, None)
            return True
        except Exception:
            return False

    async def list_jobs(self, namespace: str = "", status_filter: str = "") -> list[K8sJobRecord]:
        await self._ensure_initialized()
        ns = namespace or self._namespace
        try:
            k8s_jobs = self._batch_api.list_namespaced_job(namespace=ns)
            records = []
            for job in k8s_jobs.items:
                status = self._map_k8s_status(job)
                if status_filter and status.value != status_filter:
                    continue
                records.append(K8sJobRecord(
                    k8s_job_name=job.metadata.name,
                    k8s_namespace=job.metadata.namespace,
                    status=status,
                ))
            return records
        except Exception:
            return list(self._jobs.values())

    async def list_nodes(self) -> list[K8sNodeInfo]:
        await self._ensure_initialized()
        try:
            k8s_nodes = self._core_api.list_node()
            nodes = []
            for node in k8s_nodes.items:
                conditions = []
                ready = False
                for cond in node.status.conditions or []:
                    conditions.append({"type": cond.type, "status": cond.status})
                    if cond.type == "Ready" and cond.status == "True":
                        ready = True

                nodes.append(K8sNodeInfo(
                    node_name=node.metadata.name,
                    status="Ready" if ready else "NotReady",
                    capacity_cpu=node.status.capacity.get("cpu", "0"),
                    capacity_memory=node.status.capacity.get("memory", "0"),
                    allocatable_cpu=node.status.allocatable.get("cpu", "0"),
                    allocatable_memory=node.status.allocatable.get("memory", "0"),
                    labels=node.metadata.labels or {},
                    conditions=conditions,
                    kubelet_version=node.status.node_info.kubelet_version
                    if node.status.node_info else "",
                    os_image=node.status.node_info.os_image
                    if node.status.node_info else "",
                    architecture=node.status.node_info.architecture
                    if node.status.node_info else "amd64",
                ))
            return nodes
        except Exception as exc:
            logger.warning(f"Failed to list nodes: {exc}")
            return []

    async def get_cluster_info(self) -> K8sClusterInfo:
        await self._ensure_initialized()
        try:
            nodes = await self.list_nodes()
            from kubernetes import client
            version = client.VersionApi().get_code()
            return K8sClusterInfo(
                cluster_name="k8s-cluster",
                api_server_version=version.git_version,
                node_count=len(nodes),
                ready_nodes=sum(1 for n in nodes if n.is_ready),
                pod_count=sum(1 for _ in self._jobs.values()),
                job_count=sum(1 for r in self._jobs.values()
                            if r.status == K8sJobStatus.RUNNING),
                nodes=nodes,
            )
        except Exception as exc:
            logger.warning(f"Failed to get cluster info: {exc}")
            return K8sClusterInfo(nodes=await self.list_nodes())

    async def apply_deployment(self, spec: K8sDeploymentSpec) -> bool:
        await self._ensure_initialized()
        from kubernetes import client
        try:
            deployment = client.V1Deployment(
                metadata=client.V1ObjectMeta(name=spec.name, namespace=spec.namespace),
                spec=client.V1DeploymentSpec(
                    replicas=spec.replicas,
                    selector=client.V1LabelSelector(match_labels={"app": spec.name}),
                    template=client.V1PodTemplateSpec(
                        metadata=client.V1ObjectMeta(labels={"app": spec.name}),
                        spec=client.V1PodSpec(
                            containers=[client.V1Container(
                                name=spec.name,
                                image=spec.image,
                                ports=[client.V1ContainerPort(container_port=spec.container_port)],
                                resources=client.V1ResourceRequirements(
                                    requests=spec.resource_requests,
                                    limits=spec.resource_limits,
                                ),
                                liveness_probe=client.V1Probe(
                                    http_get=client.V1HTTPGetAction(
                                        path=spec.liveness_probe_path, port=spec.container_port
                                    ),
                                    initial_delay_seconds=spec.liveness_initial_delay,
                                    period_seconds=spec.liveness_period,
                                ),
                                readiness_probe=client.V1Probe(
                                    http_get=client.V1HTTPGetAction(
                                        path=spec.readiness_probe_path, port=spec.container_port
                                    ),
                                    initial_delay_seconds=spec.readiness_initial_delay,
                                    period_seconds=spec.readiness_period,
                                ),
                            )],
                        ),
                    ),
                ),
            )
            self._apps_api.create_namespaced_deployment(
                namespace=spec.namespace, body=deployment
            )
            return True
        except Exception as exc:
            logger.warning(f"Failed to apply deployment {spec.name}: {exc}")
            return False

    async def is_available(self) -> bool:
        try:
            await self._ensure_initialized()
            self._core_api.list_namespace(limit=1)
            return True
        except Exception:
            return False

    @staticmethod
    def _map_k8s_status(job) -> K8sJobStatus:
        """将 K8s Job 状态映射为 K8sJobStatus"""
        if not job.status:
            return K8sJobStatus.PENDING
        if job.status.succeeded:
            return K8sJobStatus.SUCCEEDED
        if job.status.failed:
            return K8sJobStatus.FAILED
        if job.status.active:
            return K8sJobStatus.RUNNING
        conditions = job.status.conditions or []
        for c in conditions:
            if c.type == "Failed":
                return K8sJobStatus.FAILED
            if c.type == "Complete":
                return K8sJobStatus.SUCCEEDED
        return K8sJobStatus.PENDING


# ─── 工厂函数 ─────────────────────────────────────────────────────────────────


class K8sClientFactory:
    """K8s 客户端工厂 —— 按环境自动选择"""

    _client: AbstractK8sClient | None = None

    @classmethod
    async def get_client(cls, force_local: bool = False) -> AbstractK8sClient:
        """获取 K8s 客户端实例（单例）"""
        if cls._client is not None:
            return cls._client

        if force_local:
            cls._client = LocalK8sClient()
            return cls._client

        # 尝试真实 K8s 客户端
        try:
            client = RealK8sClient()
            if await client.is_available():
                cls._client = client
                logger.info("K8sClientFactory: using RealK8sClient")
                return client
        except Exception:
            pass

        # 降级为本地客户端
        cls._client = LocalK8sClient()
        logger.info("K8sClientFactory: falling back to LocalK8sClient")
        return cls._client

    @classmethod
    def reset(cls) -> None:
        """重置客户端（测试用）"""
        cls._client = None
