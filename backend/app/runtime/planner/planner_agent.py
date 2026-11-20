"""
PlannerAgent — 动态 Workflow 生成引擎

核心流程:
1. 意图解析 → 结构化 PlanningGoal
2. 模板匹配 → TemplateLibrary.search()
3. 策略执行 → template_match / llm_generate / hybrid / query_expansion
4. 验证 → WorkflowValidator
5. 输出 PlanningResult

原则：
- 禁止写死 graph.add_edge()
- 所有 Workflow 由 Planner 动态生成
- 模板 + LLM 细化 = 灵活 + 可控
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.runtime.execution_engine.workflow_schema import (
    EdgeSpec,
    NodeSpec,
    NodeType,
    WorkflowSpec,
)
from app.runtime.planner.models import (
    ParameterSlot,
    PlanningGoal,
    PlanningResult,
    PlanningStrategy,
    TemplateCategory,
    TemplateLibrary,
    WorkflowTemplate,
)
from app.runtime.planner.templates import create_default_template_library
from app.runtime.planner.validator import WorkflowValidator, ValidationResult

logger = logging.getLogger(__name__)


# ============================================================================
# Intent Classification (rule-based, no LLM required)
# ============================================================================

CATEGORY_KEYWORDS: Dict[TemplateCategory, List[str]] = {
    TemplateCategory.CODE_REVIEW: ["审查", "review", "pr", "合并", "merge", "代码检查"],
    TemplateCategory.CODE_GENERATION: ["生成", "写", "实现", "开发", "创建", "构建", "generate", "create"],
    TemplateCategory.BUG_FIX: ["bug", "修复", "错误", "报错", "崩溃", "不工作", "fix", "debug"],
    TemplateCategory.DATA_ANALYSIS: ["数据", "分析", "图表", "可视化", "报告", "统计", "data", "analysis"],
    TemplateCategory.DEPLOY: ["部署", "发布", "上线", "deploy", "release", "ship"],
    TemplateCategory.QA: ["是什么", "怎么", "如何", "解释", "回答", "什么是", "为什么"],
    TemplateCategory.REFACTOR: ["重构", "优化", "整理", "refactor", "clean"],
    TemplateCategory.DOCUMENTATION: ["文档", "doc", "注释", "readme", "说明"],
    TemplateCategory.TESTING: ["测试", "test", "spec", "用例", "coverage"],
}

COMPLEXITY_PATTERNS = [
    (re.compile(r"(简单|简单任务|quick|simple)"), 2),
    (re.compile(r"(中等|medium|moderate)"), 5),
    (re.compile(r"(复杂|困难|complex|hard|difficult)"), 8),
    (re.compile(r"(大型|大型项目|整个|全部|全部代码|完整系统)"), 9),
]


def classify_intent(raw_text: str) -> PlanningGoal:
    """纯规则意图分类（无需 LLM）"""
    text_lower = raw_text.lower()

    # 分类
    best_category: Optional[TemplateCategory] = None
    best_score = 0
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = 0
        for kw in keywords:
            # 使用词边界匹配避免子串误判（如 "pr" 匹配 "production"）
            pattern = re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE)
            if pattern.search(text_lower):
                # 非英文字符也接受（中文无词边界概念）
                score += 1
            elif not kw.isascii() and kw.lower() in text_lower:
                # 中文关键词用子串匹配
                score += 1
        if score > best_score:
            best_score = score
            best_category = category

    # 复杂度
    complexity = 3  # 默认中等
    for pattern, level in COMPLEXITY_PATTERNS:
        if pattern.search(text_lower):
            complexity = level
            break

    # 关键词提取
    all_keywords = []
    for keywords_list in CATEGORY_KEYWORDS.values():
        for kw in keywords_list:
            if kw.lower() in text_lower and kw.lower() not in [k.lower() for k in all_keywords]:
                all_keywords.append(kw)

    # 实体提取（简单）
    entities: Dict[str, Any] = {}
    # 提取 language
    lang_patterns = [
        (r"\b(Python|python)\b", "Python"),
        (r"\b(JavaScript|javascript|js)\b", "JavaScript"),
        (r"\b(TypeScript|typescript|ts)\b", "TypeScript"),
        (r"\b(Go|golang)\b", "Go"),
        (r"\b(Rust|rust)\b", "Rust"),
        (r"\b(Java|java)\b", "Java"),
    ]
    for pattern, lang in lang_patterns:
        if re.search(pattern, raw_text):
            entities["language"] = lang
            break

    # 提取环境
    for env in ["production", "staging", "dev", "生产", "预发布", "测试"]:
        if env.lower() in text_lower:
            entities["environment"] = env
            break

    return PlanningGoal(
        raw_text=raw_text,
        category=best_category,
        complexity=complexity,
        keywords=all_keywords,
        entities=entities,
    )


# ============================================================================
# PlannerAgent
# ============================================================================

class PlannerAgent:
    """动态 Workflow 生成 Agent"""

    def __init__(
        self,
        template_library: Optional[TemplateLibrary] = None,
        llm_service: Any = None,  # Optional[LLMService]
        validator: Optional[WorkflowValidator] = None,
        default_model: Optional[str] = None,
        min_template_score: float = 0.3,
        llm_fallback_to_template: bool = True,
    ):
        self.template_library = template_library or create_default_template_library()
        self.llm = llm_service
        self.validator = validator or WorkflowValidator()
        # 模型默认值跟随后端配置，避免硬编码 gpt-4 与实际 provider（如 deepseek）不符
        if not default_model:
            try:
                from app.config import settings

                default_model = settings.default_llm_model or "gpt-4"
            except Exception:  # 配置不可用时退回旧默认
                default_model = "gpt-4"
        self.default_model = default_model
        self.min_template_score = min_template_score
        self.llm_fallback_to_template = llm_fallback_to_template

    async def plan(
        self,
        goal_text: str,
        strategy: Optional[PlanningStrategy] = None,
        model: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> PlanningResult:
        """
        根据目标描述生成 WorkflowSpec。

        Args:
            goal_text: 用户目标描述
            strategy: 指定策略（None=自动选择）
            model: LLM 模型
            params: 额外参数（传递给模板）

        Returns:
            PlanningResult with generated WorkflowSpec
        """
        t0 = time.time()

        # 1. 意图解析
        goal = classify_intent(goal_text)

        # 2. 选择策略
        if strategy is None:
            strategy = self._select_strategy(goal)

        # 3. 执行规划
        result = await self._execute_strategy(
            goal, strategy, model or self.default_model, params or {}
        )

        # 4. 验证
        validation = self.validator.validate(result.workflow_spec)
        if not validation.is_valid:
            # 尝试自动修复
            fixed = self._attempt_auto_fix(result.workflow_spec, validation)
            revalidation = self.validator.validate(fixed)
            if revalidation.is_valid:
                result.workflow_spec = fixed
                result.warnings.extend(
                    [f"Auto-fixed: {e.message}" for e in validation.errors]
                )
            else:
                result.warnings.extend(
                    [f"Validation error: {e.message}" for e in validation.errors]
                )
                result.confidence *= 0.5  # 严重降置信度

        result.warnings.extend(
            [f"Warning: {w.message}" for w in validation.warnings]
        )
        result.generation_time_ms = (time.time() - t0) * 1000

        return result

    def _select_strategy(self, goal: PlanningGoal) -> PlanningStrategy:
        """根据目标自动选择策略"""
        # 尝试模板匹配
        best = self.template_library.best_match(goal, self.min_template_score)
        if best:
            score, _ = best.match_score(goal)
            if score >= 0.6:  # 高匹配 → 纯模板
                return PlanningStrategy.TEMPLATE_MATCH
            else:  # 中等匹配 → 混合
                return PlanningStrategy.HYBRID

        # 无匹配 → LLM 生成
        return PlanningStrategy.LLM_GENERATE

    async def _execute_strategy(
        self,
        goal: PlanningGoal,
        strategy: PlanningStrategy,
        model: str,
        params: Dict[str, Any],
    ) -> PlanningResult:
        """执行具体规划策略"""
        if strategy == PlanningStrategy.TEMPLATE_MATCH:
            return self._plan_by_template(goal, params)
        elif strategy == PlanningStrategy.LLM_GENERATE:
            return await self._plan_by_llm(goal, model, params)
        elif strategy == PlanningStrategy.HYBRID:
            return await self._plan_hybrid(goal, model, params)
        elif strategy == PlanningStrategy.QUERY_EXPANSION:
            return await self._plan_by_expansion(goal, model, params)
        else:
            return self._plan_by_template(goal, params)  # fallback

    # ------------------------------------------------------------------
    # Strategy: Template Match
    # ------------------------------------------------------------------

    def _plan_by_template(
        self, goal: PlanningGoal, params: Dict[str, Any]
    ) -> PlanningResult:
        """纯模板匹配（最快）"""
        template = self.template_library.best_match(goal, self.min_template_score)

        if template is None:
            # 无匹配模板 → 生成最小工作流
            return self._generate_fallback_workflow(goal)

        score, _ = template.match_score(goal)
        spec = template.apply_parameters(params)

        return PlanningResult(
            workflow_spec=spec,
            strategy=PlanningStrategy.TEMPLATE_MATCH,
            template_id=template.id,
            template_score=score,
            estimated_nodes=template.estimated_nodes,
            estimated_tokens=template.estimated_tokens,
            confidence=score,
        )

    # ------------------------------------------------------------------
    # Strategy: LLM Generate
    # ------------------------------------------------------------------

    async def _plan_by_llm(
        self, goal: PlanningGoal, model: str, params: Dict[str, Any]
    ) -> PlanningResult:
        """纯 LLM 生成工作流"""
        if self.llm is None:
            if self.llm_fallback_to_template:
                logger.warning("No LLM service available, falling back to template match")
                return self._plan_by_template(goal, params)
            return self._generate_fallback_workflow(goal)

        try:
            prompt = self._build_llm_prompt(goal)
            logger.info(f"PlannerAgent: generating workflow via LLM (model={model})")

            content, usage, _ = await self.llm.chat(
                model=model,
                messages=[
                    {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=2048,
            )

            if content:
                spec = self._parse_llm_response(content)
                if spec:
                    tokens = usage.get("total_tokens", 0) if usage else 3000
                    return PlanningResult(
                        workflow_spec=spec,
                        strategy=PlanningStrategy.LLM_GENERATE,
                        estimated_nodes=len(spec.nodes),
                        estimated_tokens=tokens,
                        confidence=0.7,
                        generated_by="llm",
                    )
        except Exception as e:
            logger.error(f"LLM workflow generation failed: {e}")

        # Fallback
        if self.llm_fallback_to_template:
            return self._plan_by_template(goal, params)
        return self._generate_fallback_workflow(goal)

    # ------------------------------------------------------------------
    # Strategy: Hybrid
    # ------------------------------------------------------------------

    async def _plan_hybrid(
        self, goal: PlanningGoal, model: str, params: Dict[str, Any]
    ) -> PlanningResult:
        """模板骨架 + LLM 细化（推荐）"""
        template = self.template_library.best_match(goal, self.min_template_score)
        if template is None:
            return await self._plan_by_llm(goal, model, params)

        # 先用模板生成基础
        base_result = self._plan_by_template(goal, params)

        # LLM 细化（如有 LLM）
        if self.llm:
            try:
                refined = await self._llm_refine(base_result.workflow_spec, goal, model)
                if refined:
                    score, _ = template.match_score(goal)
                    return PlanningResult(
                        workflow_spec=refined,
                        strategy=PlanningStrategy.HYBRID,
                        template_id=template.id,
                        template_score=score,
                        estimated_nodes=len(refined.nodes),
                        estimated_tokens=template.estimated_tokens + 1500,
                        confidence=0.85,
                        generated_by="hybrid",
                    )
            except Exception as e:
                logger.warning(f"LLM refinement failed, using template as-is: {e}")

        return base_result

    # ------------------------------------------------------------------
    # Strategy: Query Expansion
    # ------------------------------------------------------------------

    async def _plan_by_expansion(
        self, goal: PlanningGoal, model: str, params: Dict[str, Any]
    ) -> PlanningResult:
        """多子目标拆解 + 编排（复杂任务）"""
        # 先用 LLM 拆解为子目标
        if self.llm:
            try:
                content, usage, _ = await self.llm.chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": DECOMPOSITION_SYSTEM_PROMPT},
                        {"role": "user", "content": f"将以下目标拆解为子目标列表:\n{goal.raw_text}"},
                    ],
                    temperature=0.3,
                    max_tokens=1024,
                )
                if content:
                    sub_goals = self._parse_sub_goals(content)
                    if sub_goals:
                        return await self._assemble_orchestrated_workflow(
                            sub_goals, goal, model, params
                        )
            except Exception as e:
                logger.warning(f"Query expansion failed: {e}")

        return await self._plan_hybrid(goal, model, params)

    # ------------------------------------------------------------------
    # LLM Prompt & Parsing
    # ------------------------------------------------------------------

    def _build_llm_prompt(self, goal: PlanningGoal) -> str:
        """构建 LLM 生成 Prompt"""
        return LLM_WORKFLOW_GEN_PROMPT.format(
            goal=goal.raw_text,
            complexity=goal.complexity,
            category=goal.category.value if goal.category else "unknown",
            language=goal.entities.get("language", "unknown"),
        )

    def _parse_llm_response(self, content: str) -> Optional[WorkflowSpec]:
        """解析 LLM 返回的 JSON 为 WorkflowSpec"""
        try:
            # 提取 JSON 块
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                # 尝试直接解析
                data = json.loads(content.strip())

            return self._dict_to_workflow_spec(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse LLM workflow response: {e}")
            return None

    def _dict_to_workflow_spec(self, data: Dict[str, Any]) -> WorkflowSpec:
        """从 dict 构建 WorkflowSpec"""
        nodes = []
        for nd in data.get("nodes", []):
            nodes.append(NodeSpec(
                id=nd["id"],
                type=NodeType(nd.get("type", "llm")),
                label=nd.get("label", nd["id"]),
                config=nd.get("config", {}),
            ))

        edges = []
        for ed in data.get("edges", []):
            edges.append(EdgeSpec(
                source=ed["from"],
                target=ed["to"],
                condition=ed.get("condition"),
            ))

        return WorkflowSpec(
            name=data.get("name", "Dynamic Workflow"),
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            entry_node=data.get("entry_node", ""),
            nodes=nodes,
            edges=edges,
        )

    async def _llm_refine(
        self, spec: WorkflowSpec, goal: PlanningGoal, model: str
    ) -> Optional[WorkflowSpec]:
        """LLM 细化模板生成的 WorkflowSpec"""
        if not self.llm:
            return None

        spec_json = spec.model_dump_json(indent=2)
        content, _, _ = await self.llm.chat(
            model=model,
            messages=[
                {"role": "system", "content": REFINEMENT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"目标: {goal.raw_text}\n当前 WorkflowSpec JSON:\n{spec_json}",
                },
            ],
            temperature=0.2,
            max_tokens=2048,
        )

        if content:
            refined = self._parse_llm_response(content)
            if refined:
                return refined
        return None

    def _parse_sub_goals(self, content: str) -> List[str]:
        """解析子目标列表"""
        sub_goals = []
        for line in content.strip().split("\n"):
            line = line.strip().lstrip("-*0123456789. ")
            if line and len(line) > 3:
                sub_goals.append(line)
        return sub_goals

    async def _assemble_orchestrated_workflow(
        self, sub_goals: List[str], goal: PlanningGoal, model: str, params: Dict[str, Any]
    ) -> PlanningResult:
        """编排多个子目标为一个主工作流"""
        # 每个子目标生成子工作流
        sub_specs: List[WorkflowSpec] = []
        total_tokens = 0

        for sg in sub_goals[:5]:  # 最多 5 个子目标
            sub_goal = PlanningGoal(
                raw_text=sg,
                category=goal.category,
                complexity=max(2, goal.complexity - 2),
            )
            sub_result = await self._execute_strategy(
                sub_goal, PlanningStrategy.TEMPLATE_MATCH, model, params
            )
            sub_specs.append(sub_result.workflow_spec)
            total_tokens += sub_result.estimated_tokens

        # 组装: 线性串联子工作流
        nodes: List[NodeSpec] = []
        edges: List[EdgeSpec] = []
        prev_end: Optional[str] = None

        for i, spec in enumerate(sub_specs):
            # 重命名节点（加前缀避免 ID 冲突）
            prefix = f"s{i}_"
            for node in spec.nodes:
                new_id = prefix + node.id
                if node.type == NodeType.START and i > 0:
                    continue  # 跳过非第一个子工作流的 START
                if node.type == NodeType.END and i < len(sub_specs) - 1:
                    continue  # 跳过非最后一个子工作流的 END
                nodes.append(NodeSpec(
                    id=new_id,
                    type=node.type,
                    label=f"[{i+1}] {node.label}",
                    config=node.config,
                ))

            for edge in spec.edges:
                new_source = prefix + edge.source
                new_target = prefix + edge.target
                # 跳过到 START 和从 END 出发的边
                base_source = prefix + "start"
                # Only add edges if both nodes exist in our new node set
                source_exists = any(n.id == new_source for n in nodes)
                target_exists = any(n.id == new_target for n in nodes)
                if source_exists and target_exists:
                    edges.append(EdgeSpec(
                        source=new_source,
                        target=new_target,
                        condition=edge.condition,
                    ))

            # 连接子工作流
            if prev_end:
                first_node = next(
                    (n for n in nodes if n.id.startswith(prefix) and n.type != NodeType.END),
                    None,
                )
                if first_node:
                    edges.append(EdgeSpec(source=prev_end, target=first_node.id))

            # 找当前子工作流的 END
            end_node = next(
                (n for n in nodes if n.id.startswith(prefix) and n.type == NodeType.END),
                None,
            )
            if end_node:
                prev_end = end_node.id

        # 添加 START
        start_node = NodeSpec(id="start", type=NodeType.START, label="开始")
        nodes.insert(0, start_node)

        # 连接 START → 第一个子工作流
        first_real = next(
            (n for n in nodes if n.type != NodeType.START and n.type != NodeType.END),
            None,
        )
        if first_real:
            edges.append(EdgeSpec(source="start", target=first_real.id))

        # 确保有 END
        if prev_end is None:
            end_node = NodeSpec(id="end", type=NodeType.END, label="结束")
            nodes.append(end_node)
            prev_end = "end"

        spec = WorkflowSpec(
            name=f"Orchestrated: {goal.raw_text[:50]}",
            description=f"Multi-goal workflow: {'; '.join(sub_goals[:3])}",
            nodes=nodes,
            edges=edges,
        )

        return PlanningResult(
            workflow_spec=spec,
            strategy=PlanningStrategy.QUERY_EXPANSION,
            estimated_nodes=len(nodes),
            estimated_tokens=total_tokens + 2000,
            confidence=0.6,
            generated_by="expansion",
        )

    # ------------------------------------------------------------------
    # Fallback & Auto-fix
    # ------------------------------------------------------------------

    def _generate_fallback_workflow(self, goal: PlanningGoal) -> PlanningResult:
        """生成最小兜底工作流（无模板/LLM 可用时）"""
        spec = WorkflowSpec(
            name=f"Minimal: {goal.raw_text[:50]}",
            description="Auto-generated fallback workflow",
            nodes=[
                NodeSpec(id="start", type=NodeType.START, label="开始"),
                NodeSpec(
                    id="execute",
                    type=NodeType.LLM,
                    label="执行任务",
                    config={
                        "system_prompt": f"完成任务: {goal.raw_text}",
                        "model": self.default_model,
                        "temperature": 0.3,
                    },
                ),
                NodeSpec(id="end", type=NodeType.END, label="结束"),
            ],
            edges=[
                EdgeSpec(source="start", target="execute"),
                EdgeSpec(source="execute", target="end"),
            ],
        )

        return PlanningResult(
            workflow_spec=spec,
            strategy=PlanningStrategy.TEMPLATE_MATCH,
            estimated_nodes=3,
            estimated_tokens=500,
            confidence=0.3,
            warnings=["No matching template or LLM available — using minimal fallback"],
        )

    def _attempt_auto_fix(
        self, spec: WorkflowSpec, validation: ValidationResult
    ) -> WorkflowSpec:
        """尝试自动修复常见验证错误"""
        spec = spec.model_copy(deep=True)

        for error in validation.errors:
            if error.code == "NO_START_NODE":
                # 添加 START 节点
                start_id = "start"
                spec.nodes.insert(0, NodeSpec(
                    id=start_id, type=NodeType.START, label="开始（自动添加）"
                ))
                first_node = next(
                    (n for n in spec.nodes if n.type != NodeType.START),
                    None,
                )
                if first_node:
                    spec.edges.insert(0, EdgeSpec(source=start_id, target=first_node.id))

            elif error.code == "NO_END_NODE":
                # 添加 END 节点
                end_id = "end"
                spec.nodes.append(NodeSpec(
                    id=end_id, type=NodeType.END, label="结束（自动添加）"
                ))
                if spec.nodes:
                    last = spec.nodes[-2] if len(spec.nodes) >= 2 else spec.nodes[0]
                    spec.edges.append(EdgeSpec(source=last.id, target=end_id))

            elif error.code == "START_HAS_INCOMING":
                # 移除到 START 的入边
                spec.edges = [
                    e for e in spec.edges
                    if not (e.target == error.node_id)
                ]

            elif error.code == "END_HAS_OUTGOING":
                # 移除从 END 出发的边
                spec.edges = [
                    e for e in spec.edges
                    if not (e.source == error.node_id)
                ]

        return spec


# ============================================================================
# LLM Prompts
# ============================================================================

PLANNER_SYSTEM_PROMPT = """你是一个专业的工作流设计专家。你的任务是根据用户目标，生成一个用 JSON 描述的 LangGraph 工作流。

工作流由节点(nodes)和边(edges)组成。节点类型有:
- "start": 工作流起点（必须恰好一个）
- "end": 工作流终点（至少一个）
- "llm": LLM 推理节点，需要 system_prompt 和 model
- "tool": 工具调用节点，需要 tool_name
- "condition": 条件分支节点，需要 expression
- "human_approval": 人工审批节点，需要 message 和 timeout_seconds

边格式: {"from": "source_id", "to": "target_id", "condition": "true/false"}

输出要求:
1. 严格 JSON 格式，放在 ```json ``` 代码块中
2. 所有条件节点必须有恰好 2 条出边（true/false）
3. 节点 ID 必须唯一
4. 工作流必须是有向无环图"""

LLM_WORKFLOW_GEN_PROMPT = """请为以下目标设计一个工作流:

目标: {goal}
复杂度: {complexity}/10
分类: {category}
语言: {language}

请生成完整的 WorkflowSpec JSON，包含:
- name: 工作流名称
- description: 简短描述
- nodes: 节点列表（必须包含一个 start 和一个 end）
- edges: 边列表

注意条件节点的 2 条出边，以及节点 ID 唯一性。"""

REFINEMENT_SYSTEM_PROMPT = """你是工作流优化专家。优化以下 WorkflowSpec JSON:
1. 检查节点顺序是否合理
2. 添加缺失的质量检查步骤
3. 确保条件分支完整（每个条件节点 2 条出边）
4. 添加错误处理路径
5. 优化 system_prompt 使其更精准
6. 保持 JSON 结构不变，只修改内容

输出优化后的完整 JSON。"""

DECOMPOSITION_SYSTEM_PROMPT = """你将复杂目标拆解为线性子目标列表。
每个子目标应该是一个独立可执行的任务。
按执行顺序排列。
每行一个子目标，格式: - 子目标描述"""


# ============================================================================
# 默认实例
# ============================================================================

_default_planner: Optional[PlannerAgent] = None


def get_default_planner(llm_service: Any = None) -> PlannerAgent:
    """获取默认 PlannerAgent 实例"""
    global _default_planner
    if _default_planner is None:
        _default_planner = PlannerAgent(llm_service=llm_service)
    return _default_planner
