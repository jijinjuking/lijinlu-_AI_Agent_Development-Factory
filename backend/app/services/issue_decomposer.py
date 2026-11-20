"""
Issue 分解引擎 — 将 Issue 分解为子任务树
复用 W17 PlannerAgent，将 WorkflowSpec 转换为可派发的任务树
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.issue import Issue
from app.models.issue_attachment import IssueAttachment
from app.runtime.planner.models import PlanningGoal, PlanningStrategy, TemplateCategory
from app.runtime.planner.planner_agent import PlannerAgent, get_default_planner

logger = logging.getLogger(__name__)

# WorkflowSpec 节点类型 → Agent 角色映射
NODE_TYPE_TO_ROLE: Dict[str, str] = {
    "llm": "developer",
    "tool": "developer",
    "condition": "reviewer",
    "human_approval": "reviewer",
    "start": "developer",
    "end": "developer",
}

# PlanningStrategy → decomposition_strategy 字符串
STRATEGY_MAP: Dict[PlanningStrategy, str] = {
    PlanningStrategy.TEMPLATE_MATCH: "template_match",
    PlanningStrategy.LLM_GENERATE: "llm_generate",
    PlanningStrategy.HYBRID: "hybrid",
    PlanningStrategy.QUERY_EXPANSION: "query_expansion",
}


class IssueDecomposer:
    """
    议题分解器：
    1. 调用 PlannerAgent 生成 WorkflowSpec
    2. 将 WorkflowSpec 转换为任务树（nodes[] + edges[]）
    3. 为每个节点分配 Agent 角色
    4. 保存回 Issue.task_tree_json
    """

    def __init__(
        self,
        db: AsyncSession,
        llm_service: Any = None,
    ):
        self.db = db
        self.planner = get_default_planner(llm_service)

    async def decompose(
        self,
        issue: Issue,
        strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        分解 Issue 为子任务树。

        Args:
            issue: Issue ORM 对象
            strategy: 分解策略（None=自动选择）

        Returns:
            task_tree dict，结构：
            {
                "version": 1,
                "root_task_id": "<uuid>",
                "nodes": [...],
                "edges": [...],
                "decomposed_at": "...",
                "strategy": "hybrid"
            }
        """
        # 1. 加载附件内容
        attachments = await self._load_attachments(issue)

        # 2. 构建 PlanningGoal（含附件内容）
        goal = self._build_goal(issue, attachments)

        # 3. 选择策略
        plan_strategy = self._parse_strategy(strategy)

        # 3. 调用 PlannerAgent（传入含附件内容的 goal.raw_text）
        logger.info(
            f"IssueDecomposer: decomposing issue {issue.id} "
            f"(strategy={plan_strategy.value if plan_strategy else 'auto'}, "
            f"attachments={len(attachments)})"
        )
        result = await self.planner.plan(
            goal_text=goal.raw_text,
            strategy=plan_strategy,
            params=self._build_params(issue),
        )

        if result.workflow_spec is None:
            raise ValueError(
                f"PlannerAgent 未能生成工作流: {result.warnings}"
            )

        # 4. WorkflowSpec → 任务树（含附件上下文）
        task_tree = self._workflow_to_task_tree(
            result.workflow_spec, issue, result.strategy, attachments
        )

        # 5. 保存回 Issue
        issue.task_tree_json = json.dumps(task_tree, ensure_ascii=False)
        issue.decomposition_strategy = STRATEGY_MAP.get(
            result.strategy, "hybrid"
        )
        issue.decomposed_at = datetime.now(timezone.utc)
        issue.status = "in_progress"

        await self.db.commit()
        await self.db.refresh(issue)

        logger.info(
            f"Issue {issue.id} decomposed: "
            f"{len(task_tree['nodes'])} nodes, "
            f"strategy={task_tree['strategy']}, "
            f"confidence={result.confidence:.2f}"
        )

        return task_tree

    def _build_goal(self, issue: Issue, attachments: list = None) -> PlanningGoal:
        """从 Issue 构建 PlanningGoal，集成附件内容"""
        raw_text = f"{issue.title}\n\n{issue.description}"

        # 拼接附件内容
        if attachments:
            raw_text += "\n\n# 附件文档内容\n\n"
            for att in attachments:
                if att.content_text:
                    raw_text += f"## {att.filename}\n\n{att.content_text}\n\n"

        return PlanningGoal(
            raw_text=raw_text,
            category=None,  # 让 PlannerAgent 自动分类
            complexity=5,  # 默认中等，可后续从 priority 推断
            keywords=[],
            entities={"issue_id": str(issue.id)},
        )

    async def _load_attachments(self, issue: Issue) -> list:
        """从数据库加载 Issue 的附件列表"""
        from sqlalchemy import select

        result = await self.db.execute(
            select(IssueAttachment)
            .where(IssueAttachment.issue_id == issue.id)
            .order_by(IssueAttachment.created_at)
        )
        return list(result.scalars().all())

    def _parse_strategy(self, strategy: Optional[str]) -> Optional[PlanningStrategy]:
        """解析策略字符串为 PlanningStrategy 枚举"""
        if strategy is None:
            return None  # 让 PlannerAgent 自动选择
        try:
            return PlanningStrategy(strategy)
        except ValueError:
            logger.warning(f"Unknown strategy '{strategy}', falling back to auto")
            return None

    def _build_params(self, issue: Issue) -> Dict[str, Any]:
        """构建模板参数"""
        return {
            "issue_title": issue.title,
            "issue_description": issue.description,
            "created_by": issue.created_by,
        }

    def _workflow_to_task_tree(
        self,
        workflow_spec: Any,  # WorkflowSpec
        issue: Issue,
        used_strategy: PlanningStrategy,
        attachments: list = None,
    ) -> Dict[str, Any]:
        """
        将 WorkflowSpec 转换为任务树结构。

        转换规则：
        - start → 虚拟根节点（不生成 Task）
        - end   → 虚拟结束节点（不生成 Task）
        - llm/tool → developer 角色任务
        - condition → reviewer 角色任务
        - human_approval → reviewer 角色任务

        每个 LLM 节点的 config.system_prompt 会注入 Issue 完整上下文
        （标题 + 描述 + 附件内容），确保 Worker 执行时能看到完整需求。
        """
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, str]] = []

        # 生成根任务 ID（对应 start 节点之后的第一个真实节点）
        root_task_id = str(uuid.uuid4())

        # 节点 ID → 任务 ID 映射
        node_to_task: Dict[str, str] = {}
        # start 节点不生成任务
        node_to_task["start"] = root_task_id  # 虚拟映射

        # 构建 Issue 完整上下文（注入到 LLM 节点的 system_prompt）
        issue_context = f"# 需求目标：{issue.title}\n\n{issue.description}"
        if attachments:
            issue_context += "\n\n# 附件文档内容\n\n"
            for att in attachments:
                if att.content_text:
                    issue_context += f"## {att.filename}\n\n{att.content_text}\n\n"

        # 第一遍：转换节点
        first_real_node: Optional[str] = None
        for i, node_spec in enumerate(workflow_spec.nodes):
            node_type = (
                node_spec.type.value
                if hasattr(node_spec.type, "value")
                else str(node_spec.type)
            )

            # 跳过 start/end
            if node_type in ("start", "end"):
                if node_type == "start":
                    node_to_task[node_spec.id] = root_task_id
                continue

            task_id = str(uuid.uuid4())
            node_to_task[node_spec.id] = task_id

            if first_real_node is None:
                first_real_node = task_id
                # 根任务 ID 等于第一个真实节点
                root_task_id = task_id

            role = NODE_TYPE_TO_ROLE.get(node_type, "developer")

            # 注入 Issue 上下文到 LLM 节点的 system_prompt
            config = dict(node_spec.config or {})
            if node_type == "llm" and issue_context:
                original_prompt = config.get("system_prompt", "")
                config["system_prompt"] = f"{original_prompt}\n\n# 任务上下文\n\n{issue_context}"

            nodes.append({
                "id": task_id,
                "parent_id": None,  # 第二遍建立父子关系
                "issue_id": str(issue.id),
                "title": node_spec.label or node_spec.id,
                "name": f"{issue.title} — {node_spec.label or node_spec.id}",
                "role": role,
                "node_type": node_type,
                "config": config,
                "status": "pending",
                "kanban_column": "todo",
            })

        # 第二遍：转换边 → 建立父子关系
        for edge_spec in workflow_spec.edges:
            source_task = node_to_task.get(edge_spec.source)
            target_task = node_to_task.get(edge_spec.target)

            if source_task and target_task:
                edges.append({
                    "from": source_task,
                    "to": target_task,
                    "condition": edge_spec.condition,
                })

                # 建立父子关系：target 的 parent_id = source
                for node in nodes:
                    if node["id"] == target_task:
                        # 避免覆盖已有的 parent（多入边取第一个）
                        if node["parent_id"] is None:
                            node["parent_id"] = source_task
                        break

        # 构建任务树
        task_tree = {
            "version": 1,
            "root_task_id": root_task_id,
            "nodes": nodes,
            "edges": edges,
            "decomposed_at": datetime.now(timezone.utc).isoformat(),
            "strategy": STRATEGY_MAP.get(used_strategy, "hybrid"),
            "workflow_name": workflow_spec.name,
            "workflow_description": workflow_spec.description,
        }

        return task_tree

    @staticmethod
    def task_tree_to_nodes(task_tree: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        将 task_tree 扁平化为节点列表（方便前端渲染树形结构）。
        """
        nodes = task_tree.get("nodes", [])
        # 建立 children 映射
        children_map: Dict[str, List[Dict]] = {}
        for node in nodes:
            parent = node.get("parent_id")
            if parent:
                children_map.setdefault(parent, []).append(node)

        # 递归构建树
        def build_tree(node: Dict) -> Dict:
            result = {k: v for k, v in node.items()}
            children = children_map.get(node["id"], [])
            if children:
                result["children"] = sorted(
                    [build_tree(c) for c in children],
                    key=lambda x: x.get("title", ""),
                )
            return result

        roots = [n for n in nodes if not n.get("parent_id")]
        return [build_tree(r) for r in roots]


async def decompose_issue(
    db: AsyncSession,
    issue_id: str,
    strategy: Optional[str] = None,
    llm_service: Any = None,
) -> Tuple[Issue, Dict[str, Any]]:
    """
    便捷函数：分解指定 Issue。

    Returns:
        (Issue ORM 对象, task_tree dict)
    """
    from sqlalchemy import select

    result = await db.execute(select(Issue).where(Issue.id == issue_id))
    issue = result.scalar_one_or_none()
    if issue is None:
        raise ValueError(f"Issue {issue_id} not found")

    decomposer = IssueDecomposer(db, llm_service)
    task_tree = await decomposer.decompose(issue, strategy)
    return issue, task_tree
