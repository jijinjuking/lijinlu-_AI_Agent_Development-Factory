"""
Workflow 验证器 — 确保 Planner 生成的 WorkflowSpec 正确可用

验证维度:
1. 结构完整性 — 有 START/END、边完整性、无重复
2. DAG 拓扑 — 无环路
3. 可达性 — 所有节点从 START 可达、所有节点可达 END
4. 类型正确性 — CONDITION 边有 condition 字段
5. 语义检查 — no orphan nodes, no dangling edges
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from app.runtime.execution_engine.workflow_schema import (
    EdgeSpec,
    NodeSpec,
    NodeType,
    WorkflowSpec,
)


@dataclass
class ValidationError:
    code: str
    message: str
    node_id: Optional[str] = None
    edge: Optional[str] = None


@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)


class WorkflowValidator:
    """WorkflowSpec 验证器"""

    def validate(self, spec: WorkflowSpec) -> ValidationResult:
        """运行全部验证"""
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []

        # 1. 结构验证（快速失败）
        errors.extend(self._validate_structure(spec))
        if errors:
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        # 2. 图验证
        graph_errors, graph_warnings = self._validate_graph(spec)
        errors.extend(graph_errors)
        warnings.extend(graph_warnings)
        warnings.extend(self._validate_warnings(spec))

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # 结构验证
    # ------------------------------------------------------------------

    def _validate_structure(self, spec: WorkflowSpec) -> List[ValidationError]:
        errors: List[ValidationError] = []

        if not spec.nodes:
            errors.append(ValidationError(
                code="EMPTY_GRAPH",
                message="WorkflowSpec has no nodes",
            ))
            return errors

        # 检查 START 节点（必须恰好一个）
        start_nodes = [n for n in spec.nodes if n.type == NodeType.START]
        if len(start_nodes) == 0:
            errors.append(ValidationError(
                code="NO_START_NODE",
                message="WorkflowSpec must have exactly one START node",
            ))
        elif len(start_nodes) > 1:
            errors.append(ValidationError(
                code="MULTIPLE_START_NODES",
                message=f"Found {len(start_nodes)} START nodes, only one allowed",
            ))

        # 检查 END 节点（至少一个）
        end_nodes = [n for n in spec.nodes if n.type == NodeType.END]
        if len(end_nodes) == 0:
            errors.append(ValidationError(
                code="NO_END_NODE",
                message="WorkflowSpec must have at least one END node",
            ))

        # 检查节点 ID 唯一性
        node_ids = [n.id for n in spec.nodes]
        if len(node_ids) != len(set(node_ids)):
            seen: Set[str] = set()
            for nid in node_ids:
                if nid in seen:
                    errors.append(ValidationError(
                        code="DUPLICATE_NODE_ID",
                        message=f"Duplicate node ID: '{nid}'",
                        node_id=nid,
                    ))
                seen.add(nid)

        if not spec.edges and len(spec.nodes) > 2:
            errors.append(ValidationError(
                code="NO_EDGES",
                message="WorkflowSpec has nodes but no edges defined",
            ))

        return errors

    # ------------------------------------------------------------------
    # 图验证（DAG + 可达性）
    # ------------------------------------------------------------------

    def _validate_graph(self, spec: WorkflowSpec) -> tuple[List[ValidationError], List[ValidationError]]:
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []

        node_ids = {n.id for n in spec.nodes}
        adjacency: Dict[str, List[str]] = {nid: [] for nid in node_ids}
        reverse_adj: Dict[str, List[str]] = {nid: [] for nid in node_ids}

        for edge in spec.edges:
            # 边端点存在性
            if edge.source not in node_ids:
                errors.append(ValidationError(
                    code="MISSING_SOURCE",
                    message=f"Edge source '{edge.source}' not found in nodes",
                    edge=f"{edge.source} -> {edge.target}",
                ))
                continue
            if edge.target not in node_ids:
                errors.append(ValidationError(
                    code="MISSING_TARGET",
                    message=f"Edge target '{edge.target}' not found in nodes",
                    edge=f"{edge.source} -> {edge.target}",
                ))
                continue

            adjacency[edge.source].append(edge.target)
            reverse_adj[edge.target].append(edge.source)

        if errors:
            return errors, warnings

        # DAG 检测（拓扑排序）— 循环不阻断执行，LangGraph 支持条件回边
        cycle_nodes = self._detect_cycle(node_ids, adjacency)
        if cycle_nodes:
            warnings.append(ValidationError(
                code="CYCLE_DETECTED",
                message=f"Cycle detected in workflow: {' → '.join(cycle_nodes)} (retry loops are legitimate in LangGraph)",
                node_id=cycle_nodes[0],
            ))

        # START 无入边
        start_nodes = [n for n in spec.nodes if n.type == NodeType.START]
        for sn in start_nodes:
            if sn.id in reverse_adj and reverse_adj[sn.id]:
                errors.append(ValidationError(
                    code="START_HAS_INCOMING",
                    message=f"START node '{sn.id}' has incoming edges",
                    node_id=sn.id,
                ))

        # END 无出边
        end_nodes = [n for n in spec.nodes if n.type == NodeType.END]
        for en in end_nodes:
            if en.id in adjacency and adjacency[en.id]:
                errors.append(ValidationError(
                    code="END_HAS_OUTGOING",
                    message=f"END node '{en.id}' has outgoing edges",
                    node_id=en.id,
                ))

        # 可达性：所有节点从 START 可达
        if start_nodes:
            reachable_from_start = self._bfs(start_nodes[0].id, adjacency)
            unreachable = node_ids - reachable_from_start
            for nid in unreachable:
                node = next(n for n in spec.nodes if n.id == nid)
                errors.append(ValidationError(
                    code="UNREACHABLE_FROM_START",
                    message=f"Node '{nid}' ({node.label}) is not reachable from START",
                    node_id=nid,
                ))

        # 可达性：所有节点可达 END
        if end_nodes:
            reachable_to_end: Set[str] = set()
            for en in end_nodes:
                reachable_to_end |= self._reverse_bfs(en.id, reverse_adj)
            unreachable_end = node_ids - reachable_to_end
            for nid in unreachable_end:
                if nid in {en.id for en in end_nodes}:
                    continue  # END 节点自身已处理
                node = next(n for n in spec.nodes if n.id == nid)
                errors.append(ValidationError(
                    code="CANNOT_REACH_END",
                    message=f"Node '{nid}' ({node.label}) cannot reach any END node",
                    node_id=nid,
                ))

        # Condition 边必须有 condition
        for edge in spec.edges:
            source_node = next((n for n in spec.nodes if n.id == edge.source), None)
            if source_node and source_node.type == NodeType.CONDITION:
                if not edge.condition:
                    errors.append(ValidationError(
                        code="CONDITION_MISSING_EXPR",
                        message=f"CONDITION node '{edge.source}' has edge to '{edge.target}' without condition",
                        node_id=edge.source,
                        edge=f"{edge.source} -> {edge.target}",
                    ))

        return errors, warnings

    # ------------------------------------------------------------------
    # 警告
    # ------------------------------------------------------------------

    def _validate_warnings(self, spec: WorkflowSpec) -> List[ValidationError]:
        warnings: List[ValidationError] = []

        # CONDITION 节点应该有恰好 2 条出边（true/false）
        cond_nodes = [n for n in spec.nodes if n.type == NodeType.CONDITION]
        for cn in cond_nodes:
            out_count = sum(1 for e in spec.edges if e.source == cn.id)
            if out_count != 2:
                warnings.append(ValidationError(
                    code="CONDITION_EDGE_COUNT",
                    message=f"CONDITION node '{cn.id}' has {out_count} outgoing edges (expected 2)",
                    node_id=cn.id,
                ))

        # LLM node 应该有 model config
        llm_nodes = [n for n in spec.nodes if n.type == NodeType.LLM]
        for ln in llm_nodes:
            if "model" not in ln.config and "system_prompt" not in ln.config:
                warnings.append(ValidationError(
                    code="LLM_MISSING_CONFIG",
                    message=f"LLM node '{ln.id}' missing model or system_prompt config",
                    node_id=ln.id,
                ))

        # 孤立节点（除 START/END 外无入边也无出边）
        for node in spec.nodes:
            if node.type in (NodeType.START, NodeType.END):
                continue
            has_in = any(e.target == node.id for e in spec.edges)
            has_out = any(e.source == node.id for e in spec.edges)
            if not has_in and not has_out:
                warnings.append(ValidationError(
                    code="ISOLATED_NODE",
                    message=f"Node '{node.id}' ({node.label}) has no connections",
                    node_id=node.id,
                ))

        return warnings

    # ------------------------------------------------------------------
    # 图算法
    # ------------------------------------------------------------------

    def _bfs(self, start: str, adjacency: Dict[str, List[str]]) -> Set[str]:
        """从 start 出发 BFS"""
        visited: Set[str] = {start}
        queue = [start]
        while queue:
            current = queue.pop(0)
            for neighbor in adjacency.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        return visited

    def _reverse_bfs(self, end: str, reverse_adj: Dict[str, List[str]]) -> Set[str]:
        """反向 BFS（从 end 出发沿 reverse_adj 遍历）"""
        visited: Set[str] = {end}
        queue = [end]
        while queue:
            current = queue.pop(0)
            for neighbor in reverse_adj.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        return visited

    def _detect_cycle(
        self, node_ids: Set[str], adjacency: Dict[str, List[str]]
    ) -> List[str]:
        """拓扑排序检测环路，返回一个环路节点序列（如有）"""
        in_degree = {nid: 0 for nid in node_ids}
        for nid, neighbors in adjacency.items():
            for neighbor in neighbors:
                in_degree[neighbor] = in_degree.get(neighbor, 0) + 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        sorted_count = 0

        while queue:
            current = queue.pop(0)
            sorted_count += 1
            for neighbor in adjacency.get(current, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if sorted_count == len(node_ids):
            return []  # 无圈

        # 有圈，从中找出一个环
        remaining = {nid for nid, deg in in_degree.items() if deg > 0}
        return self._find_cycle_path(remaining, adjacency)

    def _find_cycle_path(
        self, cycle_nodes: Set[str], adjacency: Dict[str, List[str]]
    ) -> List[str]:
        """在 cycle_nodes 中找一条环路路径"""
        visited: Set[str] = set()
        path: List[str] = []

        def dfs(node: str) -> bool:
            if node in path:
                # 找到环，截取从 node 开始的部分
                idx = path.index(node)
                path.append(node)
                nonlocal visited
                return True
            if node in visited:
                return False
            visited.add(node)
            path.append(node)
            for neighbor in adjacency.get(node, []):
                if neighbor in cycle_nodes and dfs(neighbor):
                    return True
            path.pop()
            return False

        for start in cycle_nodes:
            visited.clear()
            path.clear()
            if dfs(start):
                return path

        # 兜底：返回 cycle_nodes 中的任意链
        return list(cycle_nodes)


# ============================================================================
# 便捷函数
# ============================================================================

_default_validator = WorkflowValidator()


def validate_workflow(spec: WorkflowSpec) -> ValidationResult:
    """便捷验证函数"""
    return _default_validator.validate(spec)
