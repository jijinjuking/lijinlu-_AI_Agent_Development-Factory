"""
AI Runtime OS — K8s Job Scheduler (W25-26)

分布式 Runtime 调度器，将任务分发为 K8s Job 执行。
支持本地模拟和真实 Kubernetes 集群两种模式。

组件:
- K8sJobConfig / K8sJobRecord: Job 数据模型
- K8sNodeInfo / K8sClusterInfo: 集群信息模型
- K8sDeploymentSpec: Deployment 规格
- AbstractK8sClient: K8s 客户端抽象接口
- LocalK8sClient: 本地 subprocess 模拟客户端
- RealK8sClient: 真实 Kubernetes API 客户端
- K8sClientFactory: 自动选择客户端的工厂
- K8sJobManager: Job 生命周期管理器
- K8sScheduler: 集成 Runtime 任务与 K8s Job 的调度器
- PRESET_JOB_TEMPLATES: 预置 Job 模板
"""

from app.runtime.k8s_scheduler.models import (
    DeploymentStatus,
    K8sClusterInfo,
    K8sDeploymentSpec,
    K8sJobConfig,
    K8sJobRecord,
    K8sJobStatus,
    K8sJobType,
    K8sManifest,
    K8sNodeInfo,
)
from app.runtime.k8s_scheduler.k8s_client import (
    AbstractK8sClient,
    K8sClientFactory,
    LocalK8sClient,
    RealK8sClient,
)
from app.runtime.k8s_scheduler.job_manager import (
    K8sJobManager,
    PRESET_JOB_TEMPLATES,
)
from app.runtime.k8s_scheduler.k8s_scheduler import K8sScheduler

__all__ = [
    # Models
    "K8sJobConfig",
    "K8sJobRecord",
    "K8sJobStatus",
    "K8sJobType",
    "K8sNodeInfo",
    "K8sClusterInfo",
    "K8sDeploymentSpec",
    "K8sManifest",
    "DeploymentStatus",
    # Client
    "AbstractK8sClient",
    "LocalK8sClient",
    "RealK8sClient",
    "K8sClientFactory",
    # Manager
    "K8sJobManager",
    "PRESET_JOB_TEMPLATES",
    # Scheduler
    "K8sScheduler",
]
