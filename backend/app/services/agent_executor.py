"""
AI Runtime OS — Agent 执行引擎
负责：
1. 接收任务并执行
2. 调用 LLM 进行推理（支持 Tool Calling）
3. 通过 Tool Runtime 执行工具调用
4. 发布事件（EventBus + SSE）
5. 更新任务状态
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import event_bus, Event
from app.core.event_types import EventType
from app.core.sse_manager import sse_manager
from app.models.task import Task
from app.models.agent import Agent
from app.services.llm_service import llm_service, _calc_cost
from app.api._orm import task_to_dict
from app.runtime.state_manager.state_manager import StateManager
from app.runtime.checkpoint_manager.checkpoint_manager import CheckpointManager
from app.runtime.artifact_store import ArtifactStore
from app.runtime.tool_runtime.registry import tool_registry
from app.runtime.tool_runtime.executor import ToolExecutor
from app.runtime.tool_runtime.models import ExecutionContext, PermissionLevel
from app.runtime.context_engine import context_engine
from app.runtime.model_router.router import ModelRouter, RouterStrategy, default_router
from app.runtime.model_router.models import ModelCapability
from app.prompts import get_role_prompt, get_effective_prompt

# W18: Evaluation integration
_evaluation_enabled = True

# Agent role → 能力映射（auto 模式用）
ROLE_CAPABILITY_MAP: dict[str, set[ModelCapability]] = {
    "architect": {ModelCapability.ARCHITECTURE_DESIGN, ModelCapability.REASONING, ModelCapability.CODE_GENERATION},
    "developer": {ModelCapability.CODE_GENERATION, ModelCapability.REASONING, ModelCapability.TOOL_USE},
    "tester":     {ModelCapability.CODE_GENERATION, ModelCapability.REASONING, ModelCapability.FAST_RESPONSE},
    "reviewer":   {ModelCapability.CODE_GENERATION, ModelCapability.REASONING, ModelCapability.SUMMARIZATION},
    "deployer":   {ModelCapability.CODE_GENERATION, ModelCapability.TOOL_USE, ModelCapability.FAST_RESPONSE},
}


async def _publish_sse(event_type: str, data: dict, task_id: str):
    """推送到 SSE 频道"""
    try:
        await sse_manager.publish(event_type, data, task_id)
    except Exception:
        pass  # SSE 推送失败不影响主流程


class AgentExecutor:
    """
    Agent 执行引擎
    负责执行任务并管理执行过程，同时广播 SSE 事件
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm_service = llm_service
        self.state_mgr = StateManager(db)
        self.cp_mgr = CheckpointManager(db, self.state_mgr)
        self.artifact_store = ArtifactStore(db)
        self.tool_executor = ToolExecutor(db)
        # 确保内置工具已注册
        if tool_registry.count() == 0:
            tool_registry.register_builtins()

    async def execute(
        self,
        task_id: str,
        agent_id: str,
    ) -> Dict[str, Any]:
        """
        执行任务
        """
        task = await self._get_task(task_id)
        agent = await self._get_agent(agent_id)

        if not task:
            raise ValueError(f"Task {task_id} not found")
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        # 初始化 State
        state = await self.state_mgr.initialize(
            task_id,
            goal=task.goal_description or task.name,
        )
        state.workflow_status = "running"
        state.current_node = "executor"
        await self.state_mgr.save(task_id, state)

        # 更新任务状态为运行中
        task.status = "running"
        task.kanban_column = "in_progress"
        task.started_at = datetime.now(timezone.utc)
        await self.db.commit()

        task_dict = task_to_dict(task)

        # 保存初始 Checkpoint
        await self.cp_mgr.save_checkpoint(task_id)

        # EventBus 事件
        await event_bus.publish(Event(
            type=EventType.TASK_STARTED,
            task_id=task_id,
            payload={"agent_id": agent_id, "agent_name": agent.name},
            produced_by="agent_executor",
        ))

        # SSE 推送：任务开始
        await _publish_sse("task_started", {
            "task_id": task_id,
            "task": task_dict,
            "agent": {"id": str(agent.id), "name": agent.name, "role": agent.role},
        }, task_id)

        try:
            # SSE 推送：开始推理
            await _publish_sse("agent_thinking", {
                "task_id": task_id,
                "message": f"{agent.name} 正在分析任务...",
            }, task_id)

            result = await self._execute_task_internal(task, agent)

            # 保存执行结果为 Artifact（State 只存引用）
            artifact_id = await self.artifact_store.save(
                task_id=task_id,
                artifact_type="test_result",
                content=result,
                metadata={"agent_name": agent.name, "agent_role": agent.role},
            )

            # 保存完成 Checkpoint
            state = await self.state_mgr.load(task_id)
            if state:
                state.workflow_status = "completed"
                state.current_node = "done"
                state.add_artifact_ref(artifact_id)
                state.add_step("executor", "completed", result[:200])
                state.metadata["duration_ms"] = task.duration
                state.metadata["token_usage"] = task.token_usage
                state.metadata["cost_usd"] = task.cost
                await self.state_mgr.save(task_id, state)

            await self.cp_mgr.save_checkpoint(task_id)

            # 更新任务状态为完成
            task.status = "completed"
            task.kanban_column = "done"
            task.completed_at = datetime.now(timezone.utc)
            if task.started_at:
                _start = task.started_at
                if _start.tzinfo is None:  # SQLite 读回为 naive，统一按 UTC 处理
                    _start = _start.replace(tzinfo=timezone.utc)
                duration = (task.completed_at - _start).total_seconds() * 1000
                task.duration = int(duration)

            await self.db.commit()

            completed_dict = task_to_dict(task)

            await event_bus.publish(Event(
                type=EventType.TASK_COMPLETED,
                task_id=task_id,
                payload={"result": result, "duration_ms": task.duration, "artifact_id": artifact_id},
                produced_by="agent_executor",
            ))

            await _publish_sse("task_completed", {
                "task_id": task_id,
                "task": completed_dict,
                "result_preview": result[:200],
                "artifact_id": artifact_id,
                "duration_ms": task.duration,
                "token_usage": task.token_usage,
                "cost": task.cost,
            }, task_id)

            # W18: 触发任务完成后的自动评估
            await self._evaluate_after_execution(task_id, str(agent.id), agent.name, task, result, None)

            return {
                "status": "completed",
                "result": result,
                "task": completed_dict,
            }

        except Exception as e:
            # 保存失败 Checkpoint
            state = await self.state_mgr.load(task_id)
            if state:
                state.workflow_status = "failed"
                state.current_node = "error"
                state.error_count += 1
                state.add_step("executor", "failed", str(e)[:200])
                state.metadata["last_error"] = str(e)
                state.metadata["error_type"] = type(e).__name__
                await self.state_mgr.save(task_id, state)

            try:
                await self.cp_mgr.save_checkpoint(task_id)
            except Exception:
                logging.getLogger(__name__).warning(
                    "保存失败 Checkpoint 出错（不影响任务状态）", exc_info=True
                )

            task.status = "failed"
            task.kanban_column = "failed"
            task.completed_at = datetime.now(timezone.utc)
            if task.started_at:
                _start = task.started_at
                if _start.tzinfo is None:  # SQLite 读回为 naive，统一按 UTC 处理
                    _start = _start.replace(tzinfo=timezone.utc)
                duration = (task.completed_at - _start).total_seconds() * 1000
                task.duration = int(duration)

            await self.db.commit()

            failed_dict = task_to_dict(task)

            await event_bus.publish(Event(
                type=EventType.TASK_FAILED,
                task_id=task_id,
                payload={"error": str(e), "error_type": type(e).__name__},
                produced_by="agent_executor",
            ))

            await _publish_sse("task_failed", {
                "task_id": task_id,
                "task": failed_dict,
                "error": str(e),
                "error_type": type(e).__name__,
            }, task_id)

            # W18: 触发任务失败后的诊断评估
            await self._evaluate_after_execution(task_id, str(agent.id), agent.name, task, "", e)

            raise

    async def _resolve_model(self, agent: Agent, task: Task) -> str:
        """
        解析 Agent 使用的模型。
        - bound 模式：强制使用 agent.model 指定模型
        - auto 模式：调用 ModelRouter 动态选择最优模型
        """
        if agent.model_mode == "bound":
            return agent.model

        # auto 模式：动态路由
        role_caps = ROLE_CAPABILITY_MAP.get(agent.role, {ModelCapability.CODE_GENERATION})

        # 从任务描述估算复杂度
        desc_len = len(task.goal_description or task.name or "")
        if desc_len < 80:
            complexity = 3
        elif desc_len < 300:
            complexity = 5
        else:
            complexity = 7

        # 检查任务描述关键词调高复杂度
        complex_keywords = ["架构", "重构", "设计", "architecture", "refactor", "migrate", "优化性能"]
        if task.goal_description:
            for kw in complex_keywords:
                if kw in task.goal_description:
                    complexity = min(complexity + 2, 10)
                    break

        try:
            decision = await default_router.route(
                task_type=agent.role,
                complexity=complexity,
                required_capabilities=role_caps,
            )
            model_name = decision.model.name
            # 记录路由决策到任务日志
            await _publish_sse("model_routed", {
                "task_id": str(task.id),
                "model": model_name,
                "reason": decision.reason,
                "estimated_cost": decision.estimated_cost,
            }, str(task.id))
            return model_name
        except Exception:
            # ModelRouter 失败时回退到 agent.model
            return agent.model

    async def _execute_task_internal(
        self,
        task: Task,
        agent: Agent,
    ) -> str:
        """
        内部任务执行方法：调用 LLM 并完成推理
        支持 Tool Calling 多轮交互
        """
        MAX_TOOL_ITERATIONS = 5
        tool_schemas = self.tool_executor.get_tool_schema_for_llm()

        messages = await self._build_messages(task, agent, include_tools=bool(tool_schemas))
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        all_results: list[str] = []

        # 解析模型：bound 用指定模型，auto 用 ModelRouter 动态选
        resolved_model = await self._resolve_model(agent, task)

        for iteration in range(MAX_TOOL_ITERATIONS + 1):
            # 调用 LLM（带 tool schemas）
            content, usage, _stream, tool_calls = await self.llm_service.chat(
                model=resolved_model,
                messages=messages,
                temperature=0.7,
                max_tokens=4096,
                stream=False,
                db=self.db,
                task_id=str(task.id),
                agent_id=str(agent.id),
                agent_name=agent.name,
                task_type="task_execution",
                tools=tool_schemas if tool_schemas else None,
            )

            # 累计 token
            if usage:
                for k in total_usage:
                    total_usage[k] += usage.get(k, 0)

            # 无 tool_calls → LLM 返回最终答案
            if not tool_calls:
                content = content or "Task completed"
                all_results.append(content)
                break

            # 处理 tool calls
            await _publish_sse("tool_call_start", {
                "task_id": str(task.id),
                "iteration": iteration + 1,
                "tool_count": len(tool_calls),
            }, str(task.id))

            # 将 assistant 消息（含 tool_calls）加入对话
            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": content or ""}
            assistant_msg["tool_calls"] = []
            for tc in tool_calls:
                assistant_msg["tool_calls"].append({
                    "id": tc.get("id", f"call_{iteration}"),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": tc.get("arguments", "{}"),
                    },
                })
            messages.append(assistant_msg)

            # 执行每个 tool call
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("arguments", {})

                # 解析 JSON 参数
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except json.JSONDecodeError:
                        tool_args = {"raw": tool_args}

                tool_call_id = tc.get("id", f"call_{iteration}")

                # 通过 Tool Runtime 执行
                context = ExecutionContext(
                    task_id=str(task.id),
                    agent_id=str(agent.id),
                    agent_name=agent.name,
                    permission_level=PermissionLevel.NORMAL,
                )

                result = await self.tool_executor.execute(tool_name, tool_args, context)

                # 将 tool 结果加入对话
                tool_msg: Dict[str, Any] = {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({
                        "status": result.status.value,
                        "output": result.output,
                        "error": result.error,
                        "duration_ms": result.duration_ms,
                    }, ensure_ascii=False),
                }
                messages.append(tool_msg)

                # SSE 推送 tool call 结果
                await _publish_sse("tool_call_result", {
                    "task_id": str(task.id),
                    "tool_name": tool_name,
                    "status": result.status.value,
                    "output_preview": (result.output or "")[:200],
                    "error": result.error,
                    "duration_ms": result.duration_ms,
                }, str(task.id))

                all_results.append(f"[{tool_name}]: {result.output or result.error or 'no output'}")

            # 最后一次迭代 → 强制 LLM 输出最终答案
            if iteration >= MAX_TOOL_ITERATIONS - 1:
                messages.append({
                    "role": "system",
                    "content": "You have reached the maximum number of tool calls. Please provide a final answer now.",
                })

        # 更新 token 统计
        task.token_usage = total_usage.get("total_tokens", 0)
        task.cost = self._calculate_cost(agent.model, total_usage)
        await self.db.commit()

        await _publish_sse("token_usage", {
            "task_id": str(task.id),
            "usage": total_usage,
            "cost": task.cost,
        }, str(task.id))

        return "\n\n".join(all_results) if all_results else "Task completed"

    async def _build_messages(
        self,
        task: Task,
        agent: Agent,
        include_tools: bool = False,
    ) -> List[Dict[str, str]]:
        messages = []

        # 使用角色提示词（自定义 > 角色默认）
        system_msg = get_effective_prompt(agent.role, agent.system_prompt)

        # 附加 Agent 基本信息
        system_msg += f"\n\n你的名称是 {agent.name}，角色是 {agent.role}。"

        if include_tools:
            system_msg += "\n\n你拥有工具调用能力。在需要获取外部数据、执行代码或操作文件时使用工具。收到工具结果后分析并继续推进任务。"

        # 注入上下文（Context Engine）
        try:
            task_desc = task.goal_description or task.name or task.title or ""
            if task_desc:
                ctx_result = await context_engine.build(
                    query=task_desc,
                    project_id=str(task.project_id) if task.project_id else "",
                    token_budget=2000,
                    use_cache=True,
                )
                if ctx_result.context:
                    system_msg += f"\n\n## 相关上下文\n{ctx_result.context}"
        except Exception:
            pass  # Context 注入失败不影响主流程

        messages.append({"role": "system", "content": system_msg})

        # 任务消息：使用角色对应的 task_prefix
        role_info = get_role_prompt(agent.role)
        task_prefix = role_info.get("task_prefix", "")
        task_msg = f"{task_prefix}\n\n任务名称: {task.name}"
        if task.goal_description:
            task_msg += f"\n任务描述: {task.goal_description}"

        messages.append({"role": "user", "content": task_msg})
        return messages

    def _calculate_cost(self, model: str, usage: Dict) -> float:
        """基于 MODEL_PRICING 表的真实成本计算 (USD)"""
        return _calc_cost(
            model,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )

    # ========================================================================
    # W18: Self Evaluation Hook
    # ========================================================================

    async def _evaluate_after_execution(
        self,
        task_id: str,
        agent_id: str,
        agent_name: str,
        task: Task,
        output_result: str,
        execution_error: Exception | None,
    ) -> None:
        """任务执行完成后触发自动评估。

        非阻塞 — 评估失败不影响主流程。
        结果持久化到 evaluation_records 表。
        """
        if not _evaluation_enabled:
            return

        try:
            from app.runtime.evaluation import SelfEvaluator, EvaluatorConfig
            from app.runtime.evaluation.models import EvaluationContext, EvaluationScope

            # 收集评估上下文
            ctx = EvaluationContext(
                task_id=task_id,
                agent_name=agent_name,
                goal_description=task.goal_description or task.name or "",
                output_text=output_result or "",
                tokens_used=task.token_usage or 0,
                error_count=1 if execution_error else 0,
                recovery_count=0 if execution_error else 0,
                execution_time_ms=float(task.duration or 0),
            )

            config = EvaluatorConfig()
            evaluator = SelfEvaluator(config)

            scope = EvaluationScope.TASK
            eval_result = await evaluator.evaluate(
                task_id=task_id,
                ctx=ctx,
                scope=scope,
                agent_name=agent_name,
            )

            # 持久化到数据库
            from app.models.evaluation import EvaluationRecord
            record = EvaluationRecord.from_evaluation_result(
                eval_result,
                task_id=task_id,
                agent_name=agent_name,
            )
            record.agent_id = agent_id
            self.db.add(record)
            await self.db.commit()

            # 发布评估完成事件
            await _publish_sse("evaluation_completed", {
                "task_id": task_id,
                "evaluation_id": str(record.id),
                "overall_score": eval_result.overall_score,
                "passed": eval_result.passed,
                "issues_count": len(eval_result.issues),
                "critical_count": len(eval_result.critical_issues),
            }, task_id)

        except ImportError:
            pass  # 评估模块不可用时静默跳过
        except Exception as eval_error:
            # 评估失败不影响主流程
            import logging
            logging.getLogger(__name__).warning(
                "W18 evaluation failed for task=%s: %s", task_id, eval_error
            )

    async def _get_task(self, task_id: str) -> Optional[Task]:
        from sqlalchemy import select
        from uuid import UUID
        stmt = select(Task).where(Task.id == UUID(task_id))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_agent(self, agent_id: str) -> Optional[Agent]:
        from sqlalchemy import select
        from uuid import UUID
        stmt = select(Agent).where(Agent.id == UUID(agent_id))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
