"""
RuntimeKernel — AI Runtime OS 核心大脑。

职责：Task 生命周期、Workflow 调度、Event 分发、
      State 管理、Recovery、Checkpoint、Retry。

整合所有 Runtime 组件的统一入口。
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Set

from app.runtime.state_manager import StateManager
from app.runtime.checkpoint_manager import CheckpointManager
from app.runtime.scheduler import Scheduler, ScheduleResult
from app.runtime.policy_engine import PolicyEngine, PolicyDecision
from app.runtime.policy_engine.models import PermissionAction, PermissionResource
from app.runtime.model_router import ModelRouter, RoutingDecision
from app.runtime.loop_detector import InfiniteLoopDetector, AutoRecovery, LoopDecision
from app.runtime.sandbox import SandboxManager

logger = logging.getLogger(__name__)

# W17: Planner Agent (lazy import to avoid circular deps at module level)
_planner_imported = False
PlannerAgent = None  # type: ignore
PlanningResult = None  # type: ignore

# W18: Self Evaluator (lazy import)
_evaluator_imported = False
SelfEvaluator = None  # type: ignore


# ============================================================================
# Kernel Models
# ============================================================================

class TaskPhase(str, Enum):
    """任务执行阶段"""
    CREATED = "created"
    PLANNING = "planning"
    SCHEDULED = "scheduled"
    EXECUTING = "executing"
    PAUSED = "paused"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskRequest:
    """任务提交请求"""
    goal_description: str
    priority: int = 5
    required_capabilities: List[str] = field(default_factory=list)
    resource_requirements: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    auto_recover: bool = True


@dataclass
class TaskRecord:
    """任务记录"""
    task_id: str
    goal: str
    phase: TaskPhase = TaskPhase.CREATED
    priority: int = 5
    workflow_id: Optional[str] = None
    error_count: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KernelStatus:
    """Runtime Kernel 运行状态"""
    active_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    paused_tasks: int = 0
    total_tasks: int = 0
    total_iterations: int = 0
    uptime_seconds: float = 0.0
    version: str = "1.0.0"


# ============================================================================
# RuntimeKernel
# ============================================================================

class RuntimeKernel:
    """
    AI Runtime OS 的核心大脑。

    整合所有 Runtime 组件，提供统一的任务提交、执行、暂停、
    恢复、故障恢复接口。

    Usage:
        kernel = RuntimeKernel(
            state_manager=state_mgr,
            scheduler=scheduler,
            checkpoint_manager=ckpt_mgr,
            policy_engine=policy_engine,
            model_router=model_router,
            loop_detector=loop_detector,
            sandbox_manager=sandbox_mgr,
        )
        task_id = await kernel.submit_task(TaskRequest(
            goal_description="分析用户数据并生成报告"
        ))
        await kernel.start()
    """

    def __init__(
        self,
        state_manager: StateManager,
        scheduler: "Scheduler",
        checkpoint_manager: CheckpointManager,
        policy_engine: PolicyEngine,
        model_router: ModelRouter,
        loop_detector: InfiniteLoopDetector,
        sandbox_manager: SandboxManager,
        context_engine: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        planner_agent: Optional[Any] = None,  # W17: PlannerAgent
        llm_service: Optional[Any] = None,    # W17: LLMService for planner
        runtime_config: Optional[Dict[str, Any]] = None,  # 运行时配置（从 DB settings 加载）
    ):
        self.state_mgr = state_manager
        self.scheduler = scheduler
        self.checkpoint_mgr = checkpoint_manager
        self.policy_engine = policy_engine
        self.model_router = model_router
        self.loop_detector = loop_detector
        self.sandbox_mgr = sandbox_manager
        self.ctx_engine = context_engine
        self.event_bus = event_bus
        self.planner_agent = planner_agent  # W17
        self.llm_service = llm_service  # W17

        # ── Runtime Config ──
        cfg = runtime_config or {}
        self._max_concurrency: int = int(cfg.get("max_concurrency", 8))
        self._default_timeout_seconds: float = float(cfg.get("default_timeout_minutes", 30)) * 60
        self._auto_retry_count: int = int(cfg.get("auto_retry_count", 2))
        self._concurrency_semaphore = asyncio.Semaphore(self._max_concurrency)

        # 运行时状态
        self._tasks: Dict[str, TaskRecord] = {}
        self._running = False
        self._status = KernelStatus()
        self._start_time: float = 0.0
        self._executors: Dict[str, asyncio.Task] = {}
        self._workflows: Dict[str, Any] = {}  # W17: task_id → WorkflowSpec

        # 恢复管理器引用（懒加载注入）
        self._recovery_mgr: Optional[Any] = None
        self._auto_recovery = AutoRecovery(self.loop_detector)

    async def inject_recovery_manager(self, recovery_mgr: Any) -> None:
        """注入 Recovery Manager（避免循环依赖）"""
        self._recovery_mgr = recovery_mgr

    # =======================================================================
    # Public API
    # =======================================================================

    async def submit_task(self, task_request: TaskRequest, workflow_spec: Optional[Any] = None) -> str:
        """
        提交任务。

        支持可选 workflow_spec 参数（由 submit_task_with_workflow 传入真实 Workflow）。

        流程：
        1. 创建 Task 记录
        2. Policy Engine 预检（权限 + 预算）
        3. 进入调度队列
        4. 发布 TASK_CREATED 事件
        """
        task_id = str(uuid.uuid4())  # 合法 UUID，兼容 StateManager

        # Policy 预检
        user_id = task_request.metadata.get("user_id", "default")
        from app.runtime.policy_engine.models import PermissionAction, PermissionResource
        policy_result = self.policy_engine.check(
            task_id=task_id,
            role_names=[user_id] if user_id != "default" else ["developer"],
            action=PermissionAction.EXECUTE,
            resource=PermissionResource.AGENT,
            estimated_tokens=task_request.metadata.get("estimated_tokens") or 0,
        )
        if policy_result.decision == PolicyDecision.DENY:
            raise PermissionError(f"Task rejected by policy: {policy_result.reason}")

        # 创建 Task 记录
        task = TaskRecord(
            task_id=task_id,
            goal=task_request.goal_description,
            priority=task_request.priority,
            max_retries=self._auto_retry_count,
            metadata=task_request.metadata,
        )
        self._tasks[task_id] = task
        self._status.total_tasks += 1

        # 初始化 State（传入 goal 字符串）
        await self.state_mgr.initialize(task_id, task_request.goal_description)

        # 补充初始 state 字段
        await self.state_mgr.update_field(task_id, {
            "priority": task_request.priority,
            "phase": TaskPhase.CREATED.value,
            "messages": [],
            "artifact_refs": [],
        })

        # 入调度队列（构造 ScheduledTask）
        from app.runtime.execution_engine.workflow_schema import WorkflowSpec, NodeSpec, EdgeSpec, NodeType

        # 使用传入的 workflow_spec，或创建默认空工作流
        if workflow_spec is None:
            workflow_spec = WorkflowSpec(
                name=f"task-{task_id[:8]}",
                nodes=[
                    NodeSpec(id="start", type=NodeType.START),
                    NodeSpec(id="end", type=NodeType.END),
                ],
                edges=[EdgeSpec(source="start", target="end")],
            )

        capability = task_request.required_capabilities[0] if task_request.required_capabilities else "general"
        from app.runtime.scheduler.scheduler import ScheduledTask
        scheduled = ScheduledTask(
            task_id=task_id,
            capability=capability,
            workflow_spec=workflow_spec,
            priority=task_request.priority,
            metadata=task_request.metadata,
        )
        await self.scheduler.submit(scheduled)

        # 发布事件
        if self.event_bus:
            await self._publish_event("TASK_CREATED", task_id, {
                "goal": task_request.goal_description,
            })

        # 自动调度
        if self._running:
            asyncio.create_task(self._run_with_limits(task_id))

        self._status.active_tasks += 1
        logger.info(f"Task submitted: {task_id}")
        return task_id

    async def submit_task_spec(self, task_request: TaskRequest) -> ScheduleResult:
        """提交任务并返回调度结果（用于 Scheduler 直接集成）"""
        task_id = await self.submit_task(task_request)
        return await self.scheduler.submit_spec(
            task_id=task_id,
            priority=task_request.priority,
            capabilities=task_request.required_capabilities,
        )

    async def generate_workflow(
        self,
        goal_text: str,
        strategy: Optional[str] = None,
        model: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """
        W17: 动态生成 WorkflowSpec。

        调用 PlannerAgent 根据目标描述动态生成工作流。

        Returns:
            WorkflowSpec（Pydantic model），或 None（生成失败）
        """
        planner = self._get_or_create_planner()
        if not planner:
            logger.warning("PlannerAgent not available")
            return None

        try:
            result: Any = await planner.plan(
                goal_text=goal_text,
                strategy=strategy,
                model=model or "gpt-4",
                params=params or {},
            )
            return result.workflow_spec
        except Exception as e:
            logger.error(f"Workflow generation failed: {e}")
            return None

    async def submit_task_with_workflow(self, task_request: TaskRequest) -> str:
        """
        W17: 提交任务并自动生成 Workflow。

        修复 P0-6：先生成 Workflow，再入队（避免 Scheduler 执行空工作流）。

        流程：
        1. 调用 PlannerAgent 生成 WorkflowSpec
        2. 使用真实 Workflow 提交任务（入队）
        3. 保存 Workflow 引用
        4. 发布 WORKFLOW_GENERATED 事件
        """
        # 1. 先生成 Workflow（在入队之前）
        workflow_spec = await self.generate_workflow(
            goal_text=task_request.goal_description,
            params={
                "task_name": task_request.goal_description[:30],
                "model_name": getattr(
                    self.model_router, "default_model", "gpt-4"
                ),
            },
        )

        # 2. 使用真实 Workflow 提交任务
        task_id = await self.submit_task(task_request, workflow_spec=workflow_spec)

        # 3. 保存 Workflow 引用
        if workflow_spec:
            self._workflows[task_id] = workflow_spec
            task = self._tasks.get(task_id)
            if task:
                task.workflow_id = task_id  # 简化：workflow_id = task_id

        # 4. 发布 WORKFLOW_GENERATED 事件
        if self.event_bus and workflow_spec:
            await self._publish_event("WORKFLOW_GENERATED", task_id, {
                "workflow_name": getattr(workflow_spec, "name", "unknown"),
                "node_count": len(getattr(workflow_spec, "nodes", [])),
                "edge_count": len(getattr(workflow_spec, "edges", [])),
            })

        return task_id

    async def get_workflow(self, task_id: str) -> Optional[Any]:
        """获取任务关联的 WorkflowSpec"""
        return self._workflows.get(task_id)

    def _get_or_create_planner(self) -> Optional[Any]:
        """获取或懒加载创建 PlannerAgent"""
        global PlannerAgent, PlanningResult
        if self.planner_agent is not None:
            return self.planner_agent

        # 懒加载导入
        try:
            from app.runtime.planner import PlannerAgent as PA, get_default_planner
            self.planner_agent = get_default_planner(self.llm_service)
            return self.planner_agent
        except ImportError:
            logger.warning("Cannot import PlannerAgent — planner module not available")
            return None
        except Exception as e:
            logger.error(f"Failed to create PlannerAgent: {e}")
            return None

    # ------------------------------------------------------------------
    # W18: Self Evaluation
    # ------------------------------------------------------------------

    async def _evaluate_task(
        self, task_id: str, phase: str, error: str = ""
    ) -> None:
        """任务完成/失败后运行 Self Evaluation。"""
        global SelfEvaluator
        try:
            from app.runtime.evaluation import SelfEvaluator as SE, EvaluatorConfig
            from app.runtime.evaluation.models import EvaluationContext
        except ImportError:
            logger.debug("SelfEvaluator not available")
            return

        task = self._tasks.get(task_id)
        if not task:
            return

        try:
            state = await self.state_mgr.load(task_id)
            state_dict = state.to_dict() if hasattr(state, 'to_dict') else {}

            ctx = EvaluationContext(
                task_id=task_id,
                goal_description=task.goal or "",
                output_text=state_dict.get("output", ""),
                output_data=state_dict,
                tokens_used=state_dict.get("tokens_used", 0),
                error_count=task.error_count,
                recovery_count=1 if phase == "completed" and task.error_count > 0 else 0,
            )
            config = EvaluatorConfig()
            evaluator = SE(config)
            result = await evaluator.evaluate(
                task_id, ctx, agent_name="kernel"
            )
            logger.info(
                "W18 eval: task=%s phase=%s score=%.2f passed=%s issues=%d",
                task_id, phase, result.overall_score, result.passed, len(result.issues),
            )
            # 存入任务 metadata（后续可被前端消费）
            task.metadata["evaluation"] = result.to_dict()
        except Exception as e:
            logger.warning("W18 evaluation failed for task=%s: %s", task_id, e)

    async def pause_task(self, task_id: str, reason: str = "") -> None:
        """暂停任务（人工干预 / 策略触发）"""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        # 写 Checkpoint
        state = await self.state_mgr.load(task_id)
        await self.checkpoint_mgr.save_checkpoint(task_id, state)

        # 更新状态
        task.phase = TaskPhase.PAUSED
        await self.state_mgr.update_field(task_id, {"phase": TaskPhase.PAUSED.value})

        # 取消执行器
        executor = self._executors.pop(task_id, None)
        if executor and not executor.done():
            executor.cancel()

        if self.event_bus:
            await self._publish_event("TASK_PAUSED", task_id, {"reason": reason})

        self._status.paused_tasks += 1
        self._status.active_tasks = max(0, self._status.active_tasks - 1)

    async def resume_task(self, task_id: str, approval_data: dict = None) -> None:
        """恢复任务"""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        task.phase = TaskPhase.EXECUTING
        await self.state_mgr.update_field(task_id, {"phase": TaskPhase.EXECUTING.value})

        if approval_data:
            await self.state_mgr.update_field(task_id, {"approval_result": approval_data})

        if self._running:
            asyncio.create_task(self._run_with_limits(task_id))

        self._status.paused_tasks = max(0, self._status.paused_tasks - 1)
        self._status.active_tasks += 1

    async def cancel_task(self, task_id: str) -> None:
        """取消任务"""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        task.phase = TaskPhase.CANCELLED
        await self.state_mgr.update_field(task_id, {"phase": TaskPhase.CANCELLED.value})

        executor = self._executors.pop(task_id, None)
        if executor and not executor.done():
            executor.cancel()

        self.loop_detector.reset_task(task_id)
        self._auto_recovery.reset_recovery(task_id)

        if self.event_bus:
            await self._publish_event("TASK_CANCELLED", task_id, {})

        self._status.active_tasks = max(0, self._status.active_tasks - 1)

    async def recover_task(self, task_id: str) -> None:
        """故障恢复。"""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        task.phase = TaskPhase.RECOVERING

        # 从 Checkpoint 恢复
        try:
            checkpoint = await self.checkpoint_mgr.load_latest(task_id)
            if checkpoint:
                await self.state_mgr.save(task_id, checkpoint.state_snapshot)

            # Event Replay（如果有 Recovery Manager）
            if self._recovery_mgr:
                events = await self._recovery_mgr.replay_events(
                    task_id,
                    after_seq_num=checkpoint.event_seq_num if checkpoint else 0,
                )
                state = await self.state_mgr.load(task_id)
                for event in events:
                    state = self._apply_event(state, event)
                await self.state_mgr.save(task_id, state)

            # 重新执行
            await self.resume_task(task_id)

        except Exception as e:
            task.phase = TaskPhase.FAILED
            logger.error(f"Recovery failed for {task_id}: {e}")
            raise

    async def start(self) -> None:
        """启动 Kernel（开始处理队列中的任务）"""
        if not self._running:
            self._start_time = time.time()
        self._running = True
        logger.info("RuntimeKernel started")

    async def stop(self) -> None:
        """停止 Kernel"""
        self._running = False

        # 取消所有执行器
        for task_id, executor in list(self._executors.items()):
            if not executor.done():
                executor.cancel()
        self._executors.clear()

        self._status.active_tasks = 0
        logger.info("RuntimeKernel stopped")

    def get_status(self) -> KernelStatus:
        """获取 Kernel 运行状态"""
        self._status.uptime_seconds = (
            time.time() - self._start_time if self._start_time > 0 else 0.0
        )
        return self._status

    def get_component_statuses(self) -> dict:
        """获取各 Runtime 组件状态（供 /health 使用）"""
        def _check(obj) -> str:
            if obj is None:
                return "not_configured"
            if hasattr(obj, "is_healthy"):
                try:
                    return "ready" if obj.is_healthy() else "unhealthy"
                except Exception:
                    return "unknown"
            return "ready"

        return {
            "state_manager": _check(self.state_mgr),
            "checkpoint_manager": _check(self.checkpoint_mgr),
            "policy_engine": _check(self.policy_engine),
            "model_router": _check(self.model_router),
            "loop_detector": _check(self.loop_detector),
            "sandbox_manager": _check(self.sandbox_mgr),
            "scheduler": _check(self.scheduler),
            "event_bus": _check(self.event_bus),
            "sse_manager": _check(getattr(self, "_sse_mgr", None)),
            "context_engine": _check(self.ctx_engine),
            "planner_agent": _check(self.planner_agent),
        }

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """获取任务记录"""
        return self._tasks.get(task_id)

    def list_tasks(self, phase: Optional[str] = None) -> List[TaskRecord]:
        """列出任务"""
        tasks = list(self._tasks.values())
        if phase:
            tasks = [t for t in tasks if t.phase.value == phase]
        return tasks

    # =======================================================================
    # Internal: Task Execution Loop
    # =======================================================================

    async def _run_with_limits(self, task_id: str) -> None:
        """带并发限制和超时控制的执行包装器"""
        async with self._concurrency_semaphore:
            try:
                await asyncio.wait_for(
                    self._execute_task(task_id),
                    timeout=self._default_timeout_seconds,
                )
            except asyncio.TimeoutError:
                task = self._tasks.get(task_id)
                if task:
                    task.phase = TaskPhase.FAILED
                    self._status.failed_tasks += 1
                    self._status.active_tasks = max(0, self._status.active_tasks - 1)
                logger.warning(
                    f"Task {task_id} timed out after {self._default_timeout_seconds}s"
                )
                if self.event_bus:
                    await self._publish_event("TASK_FAILED", task_id, {
                        "error": f"Timeout after {self._default_timeout_seconds}s",
                    })

    async def _execute_task(self, task_id: str) -> None:
        """执行任务主循环"""
        task = self._tasks.get(task_id)
        if not task:
            return

        task.phase = TaskPhase.EXECUTING
        await self.state_mgr.update_field(task_id, {"phase": TaskPhase.EXECUTING.value})

        iteration = 0
        try:
            while self._running and task.phase == TaskPhase.EXECUTING:
                iteration += 1
                self._status.total_iterations += 1

                # 1. 循环检测
                loop_decision = self.loop_detector.check(
                    task_id=task_id,
                    node_id=f"iteration_{iteration}",
                    total_iterations=iteration,
                )
                if loop_decision.is_loop:
                    recovery_result = self._auto_recovery.attempt_recovery(
                        task_id=task_id,
                        decision=loop_decision,
                    )
                    if recovery_result.action.value == "human_intervention":
                        await self.pause_task(task_id, loop_decision.reason)
                        return
                    logger.warning(
                        f"Loop detected for {task_id}: {loop_decision.reason}, "
                        f"action={recovery_result.action.value}"
                    )
                    if recovery_result.action.value == "retry_with_backoff":
                        backoff = recovery_result.metadata.get("backoff_seconds", 5)
                        await asyncio.sleep(backoff)
                        self.loop_detector.reset_task(task_id)
                        iteration = 0
                        continue
                    elif recovery_result.action.value == "skip_node":
                        continue

                # 2. Policy 检查
                from app.runtime.policy_engine.models import PermissionAction, PermissionResource
                policy_result = self.policy_engine.check(
                    task_id=task_id,
                    role_names=["developer"],
                    action=PermissionAction.EXECUTE,
                    resource=PermissionResource.AGENT,
                    estimated_tokens=100,
                )
                if policy_result.decision == PolicyDecision.DENY:
                    await self.pause_task(
                        task_id, f"Policy denied: {policy_result.reason}"
                    )
                    return
                if policy_result.decision == PolicyDecision.WARN:
                    logger.warning(
                        f"Policy warning for {task_id}: {policy_result.reason}"
                    )

                # 3. 模型路由
                routing = await self.model_router.route(
                    task_id=task_id,
                    capabilities=task.metadata.get("required_capabilities", []),
                    complexity=task.metadata.get("complexity"),
                )

                # 4. 写 Checkpoint
                state = await self.state_mgr.load(task_id)
                await self.checkpoint_mgr.save_checkpoint(task_id, state)

                # 5. 执行一步（由外部注入执行逻辑）
                yield_point = await self._execute_step(task_id, iteration, routing)
                if yield_point:
                    break

        except asyncio.CancelledError:
            logger.info(f"Task {task_id} cancelled")
        except Exception as e:
            task.phase = TaskPhase.FAILED
            task.error_count += 1
            self._status.failed_tasks += 1
            self._status.active_tasks = max(0, self._status.active_tasks - 1)
            logger.error(f"Task {task_id} failed: {e}")

            # 自动恢复
            if task.error_count <= task.max_retries and task.metadata.get(
                "auto_recover", True
            ):
                logger.info(f"Auto-recovering task {task_id} (attempt {task.error_count})")
                await self.recover_task(task_id)
            else:
                await self.state_mgr.update_field(
                    task_id, {"phase": TaskPhase.FAILED.value}
                )
                if self.event_bus:
                    await self._publish_event("TASK_FAILED", task_id, {
                        "error": str(e),
                        "attempt": task.error_count,
                    })
                # W18: 任务失败后评估
                await self._evaluate_task(task_id, "failed", str(e))

    async def _execute_step(
        self, task_id: str, iteration: int, routing: RoutingDecision
    ) -> bool:
        """
        执行单个步骤。

        返回 True 表示任务完成（应退出循环）。
        子类可覆盖此方法实现自定义执行逻辑。
        """
        # 如果 iteration 达到某个阈值（由外部配置），标记完成
        max_iterations = self.loop_detector.config.max_total_iterations
        if iteration >= max_iterations * 0.5:
            # 模拟：达到一半时就标记完成
            task = self._tasks.get(task_id)
            if task:
                task.phase = TaskPhase.COMPLETED
                self._status.completed_tasks += 1
                self._status.active_tasks = max(0, self._status.active_tasks - 1)
                await self.state_mgr.update_field(
                    task_id, {"phase": TaskPhase.COMPLETED.value}
                )
                if self.event_bus:
                    await self._publish_event("TASK_COMPLETED", task_id, {
                        "iterations": iteration,
                    })
                # W18: 任务完成后评估
                await self._evaluate_task(task_id, "completed")
                return True

        # 模拟一步执行
        await asyncio.sleep(0.01)
        return False

    # =======================================================================
    # Internal: Helpers
    # =======================================================================

    async def _publish_event(
        self, event_type: str, task_id: str, payload: dict
    ) -> None:
        """发布事件（带异常保护）"""
        if not self.event_bus:
            return
        try:
            from app.core.event_bus import Event, EventType
            # 尝试匹配 EventType 枚举
            event_type_enum = event_type
            for et in EventType:
                if et.value == event_type:
                    event_type_enum = et
                    break
            event = Event(
                type=event_type_enum,
                task_id=task_id,
                payload=payload or {},
                produced_by="kernel",
            )
            await self.event_bus.publish(event)
        except Exception as e:
            logger.error(f"Failed to publish event {event_type}: {e}")

    def _apply_event(self, state: dict, event: dict) -> dict:
        """将单个 Event 应用到 State"""
        event_type = event.get("type", "")
        payload = event.get("payload", {})

        if event_type == "artifact_created":
            state.setdefault("artifact_refs", []).append(
                payload.get("artifact_id", "")
            )
        elif event_type == "message_added":
            state.setdefault("messages", []).append(payload.get("message", ""))
        elif event_type == "phase_changed":
            state["phase"] = payload.get("phase", state.get("phase"))
        elif event_type == "agent_completed":
            state["current_node"] = payload.get("next_node", "")

        return state
