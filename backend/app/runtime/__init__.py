"""
AI Runtime OS — Runtime Kernel

组件:
- State Manager (W3): LightweightState + StateManager
- Checkpoint Manager (W3): CheckpointManager
- Artifact Store (W4): ArtifactStore
- Tool Runtime (W5): ToolRegistry + ToolExecutor
- Context Engine (W6): ContextEngine
- Execution Engine (W7): LangGraphAdapter + NodeExecutor + InterruptHandler
- Scheduler (W8): TaskQueue + WorkerPool + Router + Retry/TimeoutPolicy + Scheduler
- Policy Engine (W10): PolicyEngine + TokenBudget + CostControl + PermissionEngine + Audit
- Model Router (W11): ModelRouter + ModelRegistry + ModelScorer + 动态模型路由
- Sandbox System (W12): SandboxManager + PythonSandbox + SecurityValidator + 4级安全隔离
- Loop Detector (W14): InfiniteLoopDetector + AutoRecovery + 3策略循环检测 + 4策略自动恢复
- Planner Agent (W17): PlannerAgent + TemplateLibrary + WorkflowValidator + 动态Workflow生成
- Self Evaluation (W18): SelfEvaluator + 8维度评估 + 幻觉检测 + 代码质量 + 工具指标
- Runtime Kernel: RuntimeKernel + 统一入口 + Task生命周期 + Workflow生成集成
- Recovery Manager: FailureDetector + StateRollback + RecoveryOrchestrator
- Worker Manager: WorkerRegistry + HeartbeatMonitor + WorkerScaler
- Runtime Monitor: MetricsCollector + HealthChecker
- Task Dispatcher: 任务分发到 Worker/Agent
- K8s Job Scheduler (W25-26): K8sJobManager + K8sScheduler + K8sClient + 分布式Job调度
- Multi-Node Scheduling (W27-28): NodeRegistry + CrossNodeRouter + NodeHealthChecker + 跨节点调度
- AI Marketplace (W29-30): MarketplaceRegistry + PackageManager + SearchEngine + RatingSystem + 能力包市场
- Runtime Federation (W31-32): FederationRegistry + FederationGateway + StateSyncEngine + FederationPolicyEngine + 跨集群联邦
- Multi-Tenant (W33-34): TenantManager + ResourceQuotaManager + DataIsolator + IsolationPolicy + TenantAuditLogger + 多租户隔离
- Performance Optimization (W35-36): BenchmarkRunner + MetricsCollector + ConcurrencyController + RateLimiter + LLMRateLimiter + Backpressure + ConnectionPoolOptimizer + 100并发优化
"""

# W3: State & Checkpoint
from app.runtime.state_manager import LightweightState, StateManager, StateValidator
from app.runtime.checkpoint_manager import CheckpointManager

# W4: Artifact Store
from app.runtime.artifact_store import ArtifactStore

# W5: Tool Runtime
from app.runtime.tool_runtime import ToolRegistry, ToolExecutor
from app.runtime.tool_runtime.models import ExecutionContext, ExecutionResult, ExecutionStatus

# W6: Context Engine
from app.runtime.context_engine import ContextEngine

# W7: Execution Engine
from app.runtime.execution_engine import (
    LangGraphAdapter,
    NodeExecutor,
    InterruptHandler,
    InterruptRequest,
    WorkflowState,
    WorkflowSpec,
    NodeSpec,
    EdgeSpec,
    NodeType,
    create_default_state,
    workflow_state_to_lightweight,
    lightweight_to_workflow_state,
    default_adapter,
    default_node_executor,
    interrupt_handler,
    EXAMPLE_WORKFLOW,
)

# W8: Scheduler
from app.runtime.scheduler import (
    Scheduler,
    TaskQueue,
    WorkerPool,
    Router,
    RetryPolicy,
    TimeoutPolicy,
    ScheduledTask,
    TaskStatus,
    WorkerInfo,
    Capability,
    RetryConfig,
    TimeoutConfig,
    ScheduleResult,
    default_scheduler,
)

# W10: Policy Engine
from app.runtime.policy_engine import (
    PolicyEngine,
    TokenBudget,
    TokenBudgetConfig,
    TokenUsage,
    CostControl,
    CostBudgetConfig,
    CostRecord,
    PermissionEngine,
    Permission,
    PermissionAction,
    PermissionResource,
    Role,
    AuditLogger,
    AuditAction,
    AuditEntry,
    PolicyDecision,
    PolicyResult,
    MODEL_PRICING,
    PRESET_ROLES,
)

# W11: Model Router
from app.runtime.model_router import (
    ModelRouter,
    ModelRegistry,
    ModelScorer,
    ModelSpec,
    ModelCapability,
    ComplexityTier,
    RoutingDecision,
    complexity_from_score,
    PRESET_MODELS,
    RouterStrategy,
    default_router,
    model_registry,
    default_scorer,
)

# W12: Sandbox System
from app.runtime.sandbox import (
    SandboxManager,
    PythonSandbox,
    SecurityValidator,
    SandboxType,
    SandboxStatus,
    SecurityLevel,
    SecurityPolicy,
    SandboxConfig,
    SandboxResult,
    SandboxInfo,
)

# Runtime Kernel
from app.runtime.kernel import RuntimeKernel, TaskRequest, TaskRecord, TaskPhase, KernelStatus

# Recovery Manager
from app.runtime.recovery_manager import (
    FailureDetector,
    StateRollback,
    RecoveryOrchestrator,
    FailureType,
    RecoveryAction as RMRecoveryAction,
    RecoveryStatus,
    FailureEvent,
    RecoveryPlan,
    RecoveryResult as RMRecoveryResult,
)

# Worker Manager
from app.runtime.worker_manager import (
    WorkerRegistry,
    HeartbeatMonitor,
    WorkerScaler,
    WorkerStatus as WMWorkerStatus,
    ScalingRule,
    ScalingDecision,
    ScalingDirection,
)

# Runtime Monitor
from app.runtime.runtime_monitor import (
    MetricsCollector,
    HealthChecker,
    HealthStatus,
    HealthReport,
    Metric,
    MetricType,
    RuntimeStats,
)

# Task Dispatcher
from app.runtime.task_dispatcher import TaskDispatcher

# W14: Loop Detector + Auto Recovery
from app.runtime.loop_detector import (
    InfiniteLoopDetector,
    AutoRecovery,
    LoopAction,
    LoopDecision,
    LoopDetectionConfig,
    NodeVisitRecord,
    RecoveryAction,
    RecoveryResult,
    TaskLoopStats,
)

# W17: Planner Agent — 动态 Workflow 生成
from app.runtime.planner import (
    PlannerAgent,
    PlanningGoal,
    PlanningResult,
    PlanningStrategy,
    TemplateCategory,
    TemplateLibrary,
    WorkflowTemplate,
    ParameterSlot,
    WorkflowValidator,
    ValidationError,
    ValidationResult,
    validate_workflow,
    classify_intent,
    get_default_planner,
    create_default_template_library,
    default_template_library,
)

# W18: Self Evaluation — 任务自我评估
from app.runtime.evaluation import (
    SelfEvaluator,
    EvaluatorConfig,
    Scorer,
    compute_weighted_score,
    HallucinationDetector,
    CodeQualityChecker,
    ToolMetricsCollector,
    ToolCallRecord,
)

# W25-26: K8s Job Scheduler — 分布式 Runtime
from app.runtime.k8s_scheduler import (
    K8sJobConfig,
    K8sJobRecord,
    K8sJobStatus,
    K8sJobType,
    K8sNodeInfo,
    K8sClusterInfo,
    K8sDeploymentSpec,
    K8sManifest,
    DeploymentStatus,
    AbstractK8sClient,
    LocalK8sClient,
    RealK8sClient,
    K8sClientFactory,
    K8sJobManager,
    PRESET_JOB_TEMPLATES,
    K8sScheduler,
)

# W27-28: Multi-Node Scheduling — 跨节点调度
from app.runtime.multi_node import (
    NodeInfo,
    NodeStatus,
    NodeRegistryEntry,
    NodeHeartbeat,
    RoutingDecision,
    RoutingStrategy,
    CrossNodeTask,
    ClusterTopology,
    TaskMigrationPolicy,
    NodeRegistry,
    CrossNodeRouter,
    NodeHealthChecker,
    MultiNodeScheduler,
)

# W29-30: AI Marketplace — 能力包市场
from app.runtime.marketplace import (
    MarketplaceRegistry,
    PackageManager,
    SearchEngine,
    RatingSystem,
    MarketplacePackage,
    MarketplaceStats,
    PackageRating,
    PackageStatus,
    PackageType,
    PackageVersion,
    InstallRecord,
    InstallStatus,
    LicenseType,
    ReviewRecord,
    ReviewStatus,
    SearchQuery,
    SearchResult,
)

# W31-32: Runtime Federation — 跨集群联邦
from app.runtime.federation import (
    FederationRegistry,
    FederationGateway,
    StateSyncEngine,
    FederationPolicyEngine,
    FederationMember,
    FederationCluster,
    FederationPolicyConfig,
    CrossClusterTask,
    DataSyncRecord,
    DispatchRequest,
    DispatchResult,
    FederationStats,
    JoinRequest,
    MemberHeartbeatRequest,
    FederationTopology,
    MemberStatus,
    SyncStrategy,
    SyncScope,
    DispatchPolicy,
    FederationRole,
    SyncStatus,
)

# W33-34: Multi-Tenant — 多租户隔离
from app.runtime.tenant import (
    TenantManager,
    ResourceQuotaManager,
    DataIsolator,
    IsolationPolicy,
    TenantAuditLogger,
    Tenant,
    TenantConfig,
    TenantStatus,
    TenantMember,
    TenantQuota,
    ResourceQuota,
    ResourceType,
    TenantAuditRecord,
    AuditEventType,
    AuditQuery,
    QuotaCheckResult,
    QuotaStatus,
    TenantStats,
    TenantFilter,
    IsolationMode,
    CrossTenantPolicy,
)

# W35-36: Performance Optimization — 性能优化
from app.runtime.performance import (
    BenchmarkRunner,
    MetricsCollector as PerfMetricsCollector,
    ConcurrencyController,
    RateLimiter,
    LLMRateLimiter,
    BackpressureController,
    BackpressureManager,
    ConnectionPoolOptimizer,
    BenchmarkConfig,
    BenchmarkResult,
    ConcurrencyLevelResult,
    BenchmarkSummary,
    PerformanceMetrics,
    MetricSnapshot,
    RateLimitRule,
    RateLimitResult,
    ConcurrencyConfig,
    ConcurrencyStats,
    BackpressureConfig,
    BackpressureStats,
    ConnectionPoolConfig,
    PoolStats,
    LLMRateLimitConfig,
    LLMRateLimitState,
    ConcurrencyMode,
    RateLimitAlgorithm,
    LimitScope,
    RateLimitStatus,
    BackpressureStrategy,
    MetricsAggregation,
    PRESET_RULES,
)

__all__ = [
    # W3
    "LightweightState",
    "StateManager",
    "StateValidator",
    "CheckpointManager",
    # W4
    "ArtifactStore",
    # W5
    "ToolRegistry",
    "ToolExecutor",
    "ExecutionContext",
    "ExecutionResult",
    "ExecutionStatus",
    # W6
    "ContextEngine",
    # W7
    "LangGraphAdapter",
    "NodeExecutor",
    "InterruptHandler",
    "InterruptRequest",
    "WorkflowState",
    "WorkflowSpec",
    "NodeSpec",
    "EdgeSpec",
    "NodeType",
    "create_default_state",
    "workflow_state_to_lightweight",
    "lightweight_to_workflow_state",
    "default_adapter",
    "default_node_executor",
    "interrupt_handler",
    "EXAMPLE_WORKFLOW",
    # W8
    "Scheduler",
    "TaskQueue",
    "WorkerPool",
    "Router",
    "RetryPolicy",
    "TimeoutPolicy",
    "ScheduledTask",
    "TaskStatus",
    "WorkerInfo",
    "Capability",
    "RetryConfig",
    "TimeoutConfig",
    "ScheduleResult",
    "default_scheduler",
    # W10: Policy Engine
    "PolicyEngine",
    "TokenBudget",
    "TokenBudgetConfig",
    "TokenUsage",
    "CostControl",
    "CostBudgetConfig",
    "CostRecord",
    "PermissionEngine",
    "Permission",
    "PermissionAction",
    "PermissionResource",
    "Role",
    "AuditLogger",
    "AuditAction",
    "AuditEntry",
    "PolicyDecision",
    "PolicyResult",
    "MODEL_PRICING",
    "PRESET_ROLES",
    # W11: Model Router
    "ModelRouter",
    "ModelRegistry",
    "ModelScorer",
    "ModelSpec",
    "ModelCapability",
    "ComplexityTier",
    "RoutingDecision",
    "complexity_from_score",
    "PRESET_MODELS",
    "RouterStrategy",
    "default_router",
    "model_registry",
    "default_scorer",
    # W12: Sandbox System
    "SandboxManager",
    "PythonSandbox",
    "SecurityValidator",
    "SandboxType",
    "SandboxStatus",
    "SecurityLevel",
    "SecurityPolicy",
    "SandboxConfig",
    "SandboxResult",
    "SandboxInfo",
    # W14: Loop Detector + Auto Recovery
    "InfiniteLoopDetector",
    "AutoRecovery",
    "LoopAction",
    "LoopDecision",
    "LoopDetectionConfig",
    "NodeVisitRecord",
    "RecoveryAction",
    "RecoveryResult",
    "TaskLoopStats",
    # Runtime Kernel
    "RuntimeKernel",
    "TaskRequest",
    "TaskRecord",
    "TaskPhase",
    "KernelStatus",
    # Recovery Manager
    "FailureDetector",
    "StateRollback",
    "RecoveryOrchestrator",
    "FailureType",
    "RMRecoveryAction",
    "RecoveryStatus",
    "FailureEvent",
    "RecoveryPlan",
    "RMRecoveryResult",
    # Worker Manager
    "WorkerRegistry",
    "HeartbeatMonitor",
    "WorkerScaler",
    "WMWorkerStatus",
    "ScalingRule",
    "ScalingDecision",
    "ScalingDirection",
    # Runtime Monitor
    "MetricsCollector",
    "HealthChecker",
    "HealthStatus",
    "HealthReport",
    "Metric",
    "MetricType",
    "RuntimeStats",
    # Task Dispatcher
    "TaskDispatcher",
    # W17: Planner Agent
    "PlannerAgent",
    "PlanningGoal",
    "PlanningResult",
    "PlanningStrategy",
    "TemplateCategory",
    "TemplateLibrary",
    "WorkflowTemplate",
    "ParameterSlot",
    "WorkflowValidator",
    "ValidationError",
    "ValidationResult",
    "validate_workflow",
    "classify_intent",
    "get_default_planner",
    "create_default_template_library",
    "default_template_library",
    # W18: Self Evaluation
    "SelfEvaluator",
    "EvaluatorConfig",
    "Scorer",
    "compute_weighted_score",
    "HallucinationDetector",
    "CodeQualityChecker",
    "ToolMetricsCollector",
    "ToolCallRecord",
    # W25-26: K8s Job Scheduler
    "K8sJobConfig",
    "K8sJobRecord",
    "K8sJobStatus",
    "K8sJobType",
    "K8sNodeInfo",
    "K8sClusterInfo",
    "K8sDeploymentSpec",
    "K8sManifest",
    "DeploymentStatus",
    "AbstractK8sClient",
    "LocalK8sClient",
    "RealK8sClient",
    "K8sClientFactory",
    "K8sJobManager",
    "PRESET_JOB_TEMPLATES",
    "K8sScheduler",
    # W27-28: Multi-Node Scheduling
    "NodeInfo",
    "NodeStatus",
    "NodeRegistryEntry",
    "NodeHeartbeat",
    "RoutingDecision",
    "RoutingStrategy",
    "CrossNodeTask",
    "ClusterTopology",
    "TaskMigrationPolicy",
    "NodeRegistry",
    "CrossNodeRouter",
    "NodeHealthChecker",
    "MultiNodeScheduler",
    # W29-30: AI Marketplace
    "MarketplaceRegistry",
    "PackageManager",
    "SearchEngine",
    "RatingSystem",
    "MarketplacePackage",
    "MarketplaceStats",
    "PackageRating",
    "PackageStatus",
    "PackageType",
    "PackageVersion",
    "InstallRecord",
    "InstallStatus",
    "LicenseType",
    "ReviewRecord",
    "ReviewStatus",
    "SearchQuery",
    "SearchResult",
    # W31-32: Runtime Federation
    "FederationRegistry",
    "FederationGateway",
    "StateSyncEngine",
    "FederationPolicyEngine",
    "FederationMember",
    "FederationCluster",
    "FederationPolicyConfig",
    "CrossClusterTask",
    "DataSyncRecord",
    "DispatchRequest",
    "DispatchResult",
    "FederationStats",
    "JoinRequest",
    "MemberHeartbeatRequest",
    "FederationTopology",
    "MemberStatus",
    "SyncStrategy",
    "SyncScope",
    "DispatchPolicy",
    "FederationRole",
    "SyncStatus",
    # W33-34: Multi-Tenant
    "TenantManager",
    "ResourceQuotaManager",
    "DataIsolator",
    "IsolationPolicy",
    "TenantAuditLogger",
    "Tenant",
    "TenantConfig",
    "TenantStatus",
    "TenantMember",
    "TenantQuota",
    "ResourceQuota",
    "ResourceType",
    "TenantAuditRecord",
    "AuditEventType",
    "AuditQuery",
    "QuotaCheckResult",
    "QuotaStatus",
    "TenantStats",
    "TenantFilter",
    "IsolationMode",
    "CrossTenantPolicy",
    # W35-36: Performance Optimization
    "BenchmarkRunner",
    "PerfMetricsCollector",
    "ConcurrencyController",
    "RateLimiter",
    "LLMRateLimiter",
    "BackpressureController",
    "BackpressureManager",
    "ConnectionPoolOptimizer",
    "BenchmarkConfig",
    "BenchmarkResult",
    "ConcurrencyLevelResult",
    "BenchmarkSummary",
    "PerformanceMetrics",
    "MetricSnapshot",
    "RateLimitRule",
    "RateLimitResult",
    "ConcurrencyConfig",
    "ConcurrencyStats",
    "BackpressureConfig",
    "BackpressureStats",
    "ConnectionPoolConfig",
    "PoolStats",
    "LLMRateLimitConfig",
    "LLMRateLimitState",
    "ConcurrencyMode",
    "RateLimitAlgorithm",
    "LimitScope",
    "RateLimitStatus",
    "BackpressureStrategy",
    "MetricsAggregation",
    "PRESET_RULES",
]
