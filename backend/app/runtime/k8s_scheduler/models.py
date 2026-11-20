"""
W25-26: K8s Job Scheduler — 数据模型

定义 K8s Job 调度所需的所有数据结构：
- K8sJobConfig: Job 配置
- K8sJobRecord: Job 运行记录
- K8sNodeInfo: 节点信息
- K8sDeploymentSpec: Deployment 规格
- K8sManifest: 生成的 K8s 清单
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


# ─── Enums ───────────────────────────────────────────────────────────────────


class K8sJobStatus(str, Enum):
    """K8s Job 生命周期状态"""
    CREATED = "created"
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        return self in (K8sJobStatus.SUCCEEDED, K8sJobStatus.FAILED,
                        K8sJobStatus.TIMED_OUT, K8sJobStatus.CANCELLED)

    @property
    def is_ok(self) -> bool:
        return self == K8sJobStatus.SUCCEEDED


class K8sJobType(str, Enum):
    """K8s Job 类型"""
    LANGGRAPH_WORKER = "langgraph_worker"
    API_SERVER = "api_server"
    TOOL_EXECUTOR = "tool_executor"
    SANDBOX_RUNNER = "sandbox_runner"
    CHECKPOINT_WORKER = "checkpoint_worker"
    BATCH_PROCESSOR = "batch_processor"
    CUSTOM = "custom"


class DeploymentStatus(str, Enum):
    """Deployment 运行状态"""
    PROGRESSING = "progressing"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    SCALING = "scaling"
    FAILED = "failed"


# ─── Data Classes ────────────────────────────────────────────────────────────


@dataclass
class K8sJobConfig:
    """单个 K8s Job 的完整配置"""
    job_name: str
    job_type: K8sJobType = K8sJobType.LANGGRAPH_WORKER
    image: str = "ai-runtime-os/backend:latest"
    command: list[str] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    resource_requests: dict[str, str] = field(
        default_factory=lambda: {"memory": "512Mi", "cpu": "250m"}
    )
    resource_limits: dict[str, str] = field(
        default_factory=lambda: {"memory": "2Gi", "cpu": "1000m"}
    )
    restart_policy: str = "Never"
    backoff_limit: int = 3
    active_deadline_seconds: int = 3600
    ttl_seconds_after_finished: int = 86400
    namespace: str = "ai-runtime-os"
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    node_selector: dict[str, str] = field(default_factory=dict)
    tolerations: list[dict[str, Any]] = field(default_factory=list)
    affinity: dict[str, Any] | None = None
    volumes: list[dict[str, Any]] = field(default_factory=list)
    volume_mounts: list[dict[str, Any]] = field(default_factory=list)
    service_account: str = ""
    image_pull_secrets: list[str] = field(default_factory=list)
    priority_class: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（API 友好）"""
        return {
            "job_name": self.job_name,
            "job_type": self.job_type.value,
            "image": self.image,
            "command": self.command,
            "args": self.args,
            "env_vars": self.env_vars,
            "resource_requests": self.resource_requests,
            "resource_limits": self.resource_limits,
            "restart_policy": self.restart_policy,
            "backoff_limit": self.backoff_limit,
            "active_deadline_seconds": self.active_deadline_seconds,
            "ttl_seconds_after_finished": self.ttl_seconds_after_finished,
            "namespace": self.namespace,
            "labels": self.labels,
            "annotations": self.annotations,
            "node_selector": self.node_selector,
            "tolerations": self.tolerations,
            "volumes": self.volumes,
            "volume_mounts": self.volume_mounts,
            "service_account": self.service_account,
            "priority_class": self.priority_class,
        }


@dataclass
class K8sJobRecord:
    """K8s Job 运行记录"""
    job_id: str = field(default_factory=lambda: str(uuid4()))
    task_id: str | None = None
    job_config: K8sJobConfig = field(default_factory=lambda: K8sJobConfig(job_name=""))
    status: K8sJobStatus = K8sJobStatus.CREATED
    k8s_job_name: str = ""
    k8s_namespace: str = "ai-runtime-os"
    pod_name: str = ""
    node_name: str = ""
    exit_code: int | None = None
    logs_summary: str = ""
    error_message: str | None = None
    result_data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retry_count: int = 0
    max_retries: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "task_id": self.task_id,
            "job_config": self.job_config.to_dict(),
            "status": self.status.value,
            "k8s_job_name": self.k8s_job_name,
            "k8s_namespace": self.k8s_namespace,
            "pod_name": self.pod_name,
            "node_name": self.node_name,
            "exit_code": self.exit_code,
            "logs_summary": self.logs_summary,
            "error_message": self.error_message,
            "result_data": self.result_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }


@dataclass
class K8sNodeInfo:
    """K8s 集群节点信息"""
    node_name: str
    node_ip: str = ""
    status: str = "Unknown"
    capacity_cpu: str = "0"
    capacity_memory: str = "0"
    allocatable_cpu: str = "0"
    allocatable_memory: str = "0"
    pod_count: int = 0
    max_pods: int = 110
    labels: dict[str, str] = field(default_factory=dict)
    conditions: list[dict[str, str]] = field(default_factory=list)
    kubelet_version: str = ""
    os_image: str = ""
    architecture: str = "amd64"

    @property
    def is_ready(self) -> bool:
        return self.status == "Ready"

    @property
    def cpu_usage_percent(self) -> float:
        if not self.capacity_cpu or not self.allocatable_cpu:
            return 0.0
        try:
            return (1 - float(self.allocatable_cpu) / float(self.capacity_cpu)) * 100
        except (ValueError, ZeroDivisionError):
            return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_name": self.node_name,
            "node_ip": self.node_ip,
            "status": self.status,
            "capacity_cpu": self.capacity_cpu,
            "capacity_memory": self.capacity_memory,
            "allocatable_cpu": self.allocatable_cpu,
            "allocatable_memory": self.allocatable_memory,
            "pod_count": self.pod_count,
            "max_pods": self.max_pods,
            "labels": self.labels,
            "kubelet_version": self.kubelet_version,
            "os_image": self.os_image,
            "architecture": self.architecture,
            "is_ready": self.is_ready,
            "cpu_usage_percent": self.cpu_usage_percent,
        }


@dataclass
class K8sDeploymentSpec:
    """K8s Deployment 完整规格"""
    name: str
    namespace: str = "ai-runtime-os"
    replicas: int = 1
    image: str = "ai-runtime-os/backend:latest"
    image_pull_policy: str = "IfNotPresent"
    container_port: int = 8000
    command: list[str] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    env_from_secrets: list[str] = field(default_factory=list)
    liveness_probe_path: str = "/health"
    readiness_probe_path: str = "/health"
    liveness_initial_delay: int = 30
    liveness_period: int = 10
    readiness_initial_delay: int = 10
    readiness_period: int = 5
    resource_requests: dict[str, str] = field(
        default_factory=lambda: {"memory": "256Mi", "cpu": "250m"}
    )
    resource_limits: dict[str, str] = field(
        default_factory=lambda: {"memory": "1Gi", "cpu": "1000m"}
    )
    service_port: int = 80
    service_target_port: int = 8000
    service_type: str = "ClusterIP"
    node_selector: dict[str, str] = field(default_factory=dict)
    volumes: list[dict[str, Any]] = field(default_factory=list)
    volume_mounts: list[dict[str, Any]] = field(default_factory=list)
    service_account: str = ""
    pod_annotations: dict[str, str] = field(default_factory=dict)
    revision_history_limit: int = 3
    strategy_type: str = "RollingUpdate"
    max_surge: str = "25%"
    max_unavailable: str = "25%"
    pod_disruption_budget_min: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "namespace": self.namespace,
            "replicas": self.replicas,
            "image": self.image,
            "container_port": self.container_port,
            "command": self.command,
            "env_vars": self.env_vars,
            "service_type": self.service_type,
            "resource_requests": self.resource_requests,
            "resource_limits": self.resource_limits,
        }


@dataclass
class K8sManifest:
    """生成的 K8s 清单文件"""
    content: str
    file_name: str
    kind: str  # Job / Deployment / Service / ConfigMap / etc.
    namespace: str = "ai-runtime-os"


@dataclass
class K8sClusterInfo:
    """K8s 集群概览"""
    cluster_name: str = "ai-runtime-os"
    api_server_version: str = ""
    node_count: int = 0
    ready_nodes: int = 0
    total_cpu: str = "0"
    total_memory: str = "0"
    pod_count: int = 0
    job_count: int = 0
    namespace_count: int = 0
    nodes: list[K8sNodeInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_name": self.cluster_name,
            "api_server_version": self.api_server_version,
            "node_count": self.node_count,
            "ready_nodes": self.ready_nodes,
            "total_cpu": self.total_cpu,
            "total_memory": self.total_memory,
            "pod_count": self.pod_count,
            "job_count": self.job_count,
            "namespace_count": self.namespace_count,
            "nodes": [n.to_dict() for n in self.nodes],
        }
