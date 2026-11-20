"""
Issue 任务派发引擎 — 将分解后的任务树派发到对应 Agent
"""
from __future__ import annotations

import json
import logging
import uuid as uuid_module
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.issue import Issue
from app.models.task import Task

logger = logging.getLogger(__name__)


class IssueTaskDispatcher:
    """
    议题任务派发器：
    1. 读取 Issue.task_tree_json
    2. 为每个节点创建 Task 记录
    3. 按角色匹配 Agent（自动分配或手动指定）
    4. 建立父子任务关系
    5. 返回派发结果
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def dispatch_all(
        self,
        issue: Issue,
        auto_assign: bool = True,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> DispatchResult:
        """
        派发 Issue 下所有子任务。

        Args:
            issue: Issue ORM 对象
            auto_assign: 是否自动按角色匹配 Agent
            overrides: 节点级别覆盖（可选），如 {"node_id": {"agent_id": "..."}}

        Returns:
            DispatchResult 包含派发统计和创建的任务列表
        """
        if not issue.task_tree_json:
            raise ValueError("Issue 尚未分解，请先调用 decompose")

        task_tree = (
            json.loads(issue.task_tree_json)
            if isinstance(issue.task_tree_json, str)
            else issue.task_tree_json
        )

        nodes = task_tree.get("nodes", [])
        if not nodes:
            raise ValueError("任务树为空，没有可派发的节点")

        overrides = overrides or {}

        # 第一遍：创建所有 Task 记录（先不建立关系）
        created_map: Dict[str, Task] = {}  # node_id → Task
        stats = DispatchStats(total=len(nodes))

        for node in nodes:
            node_id = node["id"]
            override = overrides.get(node_id, {})

            agent = await self._pick_agent(
                role=override.get("role") or node.get("role", "developer"),
                auto_assign=auto_assign,
                preferred_agent_id=override.get("agent_id"),
            )

            task = Task(
                id=uuid_module.UUID(node_id),
                name=node.get("name", node.get("title", "子任务")),
                goal_description=node.get("config", {}).get(
                    "system_prompt",
                    node.get("title", ""),
                ),
                title=node.get("title", ""),
                status="pending",
                kanban_column="todo",
                issue_id=issue.id,
                agent_id=agent.id if agent else None,
                agent_name=agent.name if agent else "",
                priority=issue.priority,
                tags="",
            )

            self.db.add(task)
            created_map[node_id] = task

            if agent:
                stats.assigned += 1
            else:
                stats.unassigned += 1

        # 提交创建（让所有 Task 有 ID 后才能建立关系）
        await self.db.flush()

        # 第二遍：建立父子关系
        for node in nodes:
            node_id = node["id"]
            parent_id = node.get("parent_id")

            if parent_id and parent_id in created_map:
                task = created_map[node_id]
                task.parent_task_id = uuid_module.UUID(parent_id)

        # 更新 Issue 状态
        issue.status = "in_progress"

        await self.db.commit()

        # 转换为响应格式
        dispatched = [
            self._task_to_dict(t, task_tree)
            for t in created_map.values()
        ]

        logger.info(
            f"Issue {issue.id} dispatch complete: "
            f"{stats.assigned} assigned, {stats.unassigned} unassigned"
        )

        return DispatchResult(
            issue_id=str(issue.id),
            stats=stats,
            tasks=dispatched,
            task_tree=task_tree,
        )

    async def dispatch_single(
        self,
        issue: Issue,
        node_id: str,
        agent_id: Optional[str] = None,
        agent_role: Optional[str] = None,
    ) -> Optional[Task]:
        """
        派发单个节点（手动调整后重新派发）。

        Args:
            issue: Issue ORM
            node_id: 任务树节点 ID
            agent_id: 指定 Agent（覆盖自动匹配）
            agent_role: 指定角色（覆盖节点角色）

        Returns:
            创建的 Task
        """
        task_tree = (
            json.loads(issue.task_tree_json)
            if isinstance(issue.task_tree_json, str)
            else issue.task_tree_json
        )

        nodes = task_tree.get("nodes", [])
        node = next((n for n in nodes if n["id"] == node_id), None)
        if not node:
            raise ValueError(f"节点 {node_id} 不在任务树中")

        role = agent_role or node.get("role", "developer")

        if agent_id:
            try:
                agent_uid = uuid_module.UUID(agent_id)
            except ValueError:
                raise ValueError(f"无效的 agent_id: {agent_id}")
            result = await self.db.execute(
                select(Agent).where(Agent.id == agent_uid)
            )
            agent = result.scalar_one_or_none()
        else:
            agent = await self._pick_agent(role, auto_assign=True)

        task = Task(
            id=uuid_module.UUID(node_id),
            name=node.get("name", node.get("title", "子任务")),
            goal_description=node.get("config", {}).get("system_prompt", ""),
            title=node.get("title", ""),
            status="pending",
            kanban_column="todo",
            issue_id=issue.id,
            agent_id=agent.id if agent else None,
            agent_name=agent.name if agent else "",
            priority=issue.priority,
            parent_task_id=(
                uuid_module.UUID(node["parent_id"])
                if node.get("parent_id")
                else None
            ),
        )

        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)

        return task

    async def _pick_agent(
        self,
        role: str,
        auto_assign: bool = True,
        preferred_agent_id: Optional[str] = None,
    ) -> Optional[Agent]:
        """
        按角色匹配 Agent。

        匹配规则：
        1. 如果指定了 preferred_agent_id，直接返回该 Agent
        2. 按 role 查询 idle Agent
        3. 如果无 idle Agent，选一个 active 的
        4. 如果都无，返回 None（待分配）
        """
        if preferred_agent_id:
            try:
                agent_uid = uuid_module.UUID(preferred_agent_id)
            except ValueError:
                return None
            result = await self.db.execute(
                select(Agent).where(
                    Agent.id == agent_uid,
                    Agent.is_active == True,
                )
            )
            return result.scalar_one_or_none()

        if not auto_assign:
            return None

        # 按 role + idle 优先匹配
        result = await self.db.execute(
            select(Agent).where(
                Agent.role == role,
                Agent.status == "idle",
                Agent.is_active == True,
            )
        )
        agent = result.scalars().first()

        if not agent:
            # 降级：任意 active Agent
            result = await self.db.execute(
                select(Agent).where(
                    Agent.role == role,
                    Agent.is_active == True,
                )
            )
            agent = result.scalars().first()

        return agent

    def _task_to_dict(self, task: Task, task_tree: Dict) -> Dict[str, Any]:
        """将 Task ORM 对象转为响应 dict"""
        return {
            "id": str(task.id),
            "name": task.name,
            "title": task.title,
            "status": task.status,
            "kanban_column": task.kanban_column,
            "agent_id": str(task.agent_id) if task.agent_id else None,
            "agent_name": task.agent_name or "",
            "priority": task.priority,
            "issue_id": str(task.issue_id) if task.issue_id else None,
            "parent_task_id": (
                str(task.parent_task_id) if task.parent_task_id else None
            ),
        }


# ============================================================================
# 结果类型
# ============================================================================

class DispatchStats:
    def __init__(self, total: int = 0, assigned: int = 0, unassigned: int = 0):
        self.total = total
        self.assigned = assigned
        self.unassigned = unassigned

    def to_dict(self) -> Dict[str, int]:
        return {
            "total": self.total,
            "assigned": self.assigned,
            "unassigned": self.unassigned,
        }


class DispatchResult:
    def __init__(
        self,
        issue_id: str,
        stats: DispatchStats,
        tasks: List[Dict[str, Any]],
        task_tree: Dict[str, Any],
    ):
        self.issue_id = issue_id
        self.stats = stats
        self.tasks = tasks
        self.task_tree = task_tree

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "stats": self.stats.to_dict(),
            "tasks": self.tasks,
            "task_tree": self.task_tree,
        }


# ============================================================================
# 便捷函数
# ============================================================================


async def dispatch_issue_tasks(
    db: AsyncSession,
    issue_id: str,
    auto_assign: bool = True,
    overrides: Optional[Dict[str, Any]] = None,
) -> DispatchResult:
    """
    便捷函数：派发指定 Issue 的所有子任务。
    """
    result = await db.execute(
        select(Issue).where(Issue.id == uuid_module.UUID(issue_id))
    )
    issue = result.scalar_one_or_none()
    if issue is None:
        raise ValueError(f"Issue {issue_id} not found")

    dispatcher = IssueTaskDispatcher(db)
    return await dispatcher.dispatch_all(
        issue,
        auto_assign=auto_assign,
        overrides=overrides,
    )
