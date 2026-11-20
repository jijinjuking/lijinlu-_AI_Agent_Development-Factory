"""
W14: 无限循环检测 + 自动恢复 — 核心实现

InfiniteLoopDetector: 三策略循环检测
  1. 单节点访问次数超限
  2. 最近 N 个节点序列重复（Floyd 变体 + 序列匹配）
  3. 总迭代次数超限

AutoRecovery: 四策略自动恢复
  1. 替代路径
  2. 从 Checkpoint 恢复
  3. 指数退避重试
  4. 人工介入（兜底）
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.runtime.loop_detector.models import (
    LoopAction,
    LoopDecision,
    LoopDetectionConfig,
    RecoveryAction,
    RecoveryResult,
    TaskLoopStats,
)


class InfiniteLoopDetector:
    """
    无限循环检测器。

    在 LangGraph 工作流每个节点执行前调用 check()，
    维护任务级别的访问统计，三种策略并行检测。

    使用示例:
        detector = InfiniteLoopDetector()
        decision = await detector.check("task-001", "agent_node")
        if decision.is_loop:
            await handle_loop(decision)
    """

    def __init__(self, config: Optional[LoopDetectionConfig] = None):
        self.config = config or LoopDetectionConfig()
        # task_id -> {node_name: count}
        self._node_visit_counts: Dict[str, Dict[str, int]] = defaultdict(dict)
        # task_id -> [node_names]
        self._node_sequences: Dict[str, List[str]] = defaultdict(list)
        # task_id -> total_iteration_count
        self._total_iterations: Dict[str, int] = defaultdict(int)

    # ── Public API ──────────────────────────────────────────────

    async def check(self, task_id: str, current_node: str) -> LoopDecision:
        """
        检测任务是否进入无限循环。

        在每次节点执行前调用，记录访问并执行三种策略检测。
        检测优先级：单节点 > 序列重复 > 总迭代（按严重程度递增）。
        """
        # 记录访问
        self._node_visit_counts[task_id][current_node] = (
            self._node_visit_counts[task_id].get(current_node, 0) + 1
        )
        self._node_sequences[task_id].append(current_node)
        self._total_iterations[task_id] += 1

        # 策略 3（总迭代）优先 — 最严重
        total = self._total_iterations[task_id]
        if total > self.config.max_total_iterations:
            return LoopDecision(
                is_loop=True,
                reason=(
                    f"任务 '{task_id}' 总迭代 {total} 次，"
                    f"超过阈值 {self.config.max_total_iterations}"
                ),
                action=LoopAction.ABORT,
                suggestion="任务执行规模过大，建议检查工作流设计或拆分任务",
            )

        # 策略 1：单节点超限
        node_count = self._node_visit_counts[task_id][current_node]
        if node_count > self.config.max_node_visits:
            return LoopDecision(
                is_loop=True,
                reason=(
                    f"节点 '{current_node}' 访问 {node_count} 次，"
                    f"超过阈值 {self.config.max_node_visits}"
                ),
                action=LoopAction.PAUSE,
                suggestion=(
                    f"节点 '{current_node}' 的出边条件可能有问题，"
                    f"检查条件逻辑确保有退出路径"
                ),
            )

        # 策略 2：序列重复检测
        sequence = self._node_sequences[task_id]
        if len(sequence) >= self.config.sequence_window:
            recent = sequence[-self.config.sequence_window:]
            cycle_info = self._detect_cycle(recent)
            if cycle_info:
                return LoopDecision(
                    is_loop=True,
                    reason=f"检测到循环序列: {cycle_info}",
                    action=LoopAction.PAUSE,
                    suggestion="条件边存在逻辑缺陷，检查循环退出条件",
                )

        return LoopDecision(is_loop=False)

    def reset_task(self, task_id: str) -> None:
        """重置任务统计数据（任务完成后或恢复重试前调用）"""
        self._node_visit_counts.pop(task_id, None)
        self._node_sequences.pop(task_id, None)
        self._total_iterations.pop(task_id, None)

    def get_task_stats(self, task_id: str) -> TaskLoopStats:
        """获取任务循环统计信息"""
        node_counts = self._node_visit_counts.get(task_id, {})
        top_nodes = sorted(node_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return TaskLoopStats(
            task_id=task_id,
            total_iterations=self._total_iterations.get(task_id, 0),
            unique_nodes=len(node_counts),
            top_nodes=top_nodes,
        )

    def active_tasks(self) -> List[str]:
        """获取当前活跃任务列表"""
        return list(self._total_iterations.keys())

    # ── Internal ────────────────────────────────────────────────

    def _detect_cycle(self, recent_nodes: List[str]) -> Optional[str]:
        """
        检测最近节点序列是否形成循环。

        策略：
        1. 从最短循环长度开始，检查最后 cycle_len*2 个节点是否形成重复
        2. 使用 Floyd 判圈算法作为补充检测
        """
        n = len(recent_nodes)

        # 策略 A：直接序列匹配
        for cycle_len in range(
            self.config.min_cycle_length,
            min(self.config.max_cycle_length + 1, n // 2 + 1),
        ):
            if n >= cycle_len * 2:
                a = recent_nodes[-cycle_len * 2 : -cycle_len]
                b = recent_nodes[-cycle_len:]
                if a == b:
                    # 跳过全部相同节点的"循环"（由策略 1 处理）
                    if len(set(a)) == 1:
                        continue
                    return f"序列 {a} 连续重复，长度 {cycle_len}"

        # 策略 B：Floyd 判圈（适用于更长周期）
        floyd_result = self._floyd_detect(recent_nodes)
        if floyd_result:
            return floyd_result

        return None

    def _floyd_detect(self, nodes: List[str]) -> Optional[str]:
        """
        Floyd 判圈算法（龟兔赛跑）。

        将节点序列视为链表，检测是否存在循环。
        序列中重复的节点名表示回到了同一状态。
        """
        n = len(nodes)
        if n < 4:
            return None

        # 从序列末尾向前搜索重复的节点对
        # 使用 hash 加速查找
        seen = {}
        for i in range(n - 1, -1, -1):
            node = nodes[i]
            if node in seen:
                # 找到了重复出现，计算周期
                cycle_len = seen[node] - i
                if self.config.min_cycle_length <= cycle_len <= self.config.max_cycle_length:
                    # 确认这个周期重复了至少 2 次
                    cycle = nodes[i : i + cycle_len]
                    if n >= i + cycle_len * 2:
                        if nodes[i + cycle_len : i + cycle_len * 2] == cycle:
                            return f"Floyd 检测到周期 {cycle_len}: {cycle}"
            seen[node] = i

        return None


class AutoRecovery:
    """
    自动恢复引擎。

    当 InfiniteLoopDetector 检测到循环时，根据循环类型选择合适的恢复策略。
    支持多级恢复：先尝试自动化策略，失败后升级到人工介入。

    使用示例:
        recovery = AutoRecovery(detector)
        result = await recovery.attempt_recovery("task-001", decision)
        if not result.success:
            await notify_admin(task_id, result.message)
    """

    def __init__(self, detector: InfiniteLoopDetector):
        self.detector = detector
        # task_id -> [RecoveryResult]
        self._recovery_history: Dict[str, List[RecoveryResult]] = defaultdict(list)

    async def attempt_recovery(
        self, task_id: str, decision: LoopDecision
    ) -> RecoveryResult:
        """
        尝试自动恢复。

        根据循环原因选择合适的恢复策略，
        如果已达最大重试次数则转为人工介入。
        """
        retry_count = len(self._recovery_history[task_id])

        # 超过最大重试次数 → 人工介入
        if retry_count >= self.detector.config.recovery_max_retries:
            result = RecoveryResult(
                success=False,
                action=RecoveryAction.HUMAN_INTERVENTION,
                message=(
                    f"已达最大重试次数 {self.detector.config.recovery_max_retries}，"
                    f"需要人工介入。历史恢复记录: {len(self._recovery_history[task_id])} 次"
                ),
            )
            self._recovery_history[task_id].append(result)
            return result

        # 根据循环类型选择策略
        action = self._select_recovery_action(decision)
        backoff_seconds = self._calculate_backoff(retry_count)

        if action == RecoveryAction.RETRY_WITH_BACKOFF:
            message = (
                f"指数退避重试（第 {retry_count + 1} 次），"
                f"等待 {backoff_seconds:.1f}s 后重置任务状态"
            )
        elif action == RecoveryAction.ALTERNATIVE_PATH:
            message = f"跳过循环节点，尝试替代路径（第 {retry_count + 1} 次）"
        elif action == RecoveryAction.CONTINUE_FROM_CHECKPOINT:
            message = f"从最近 Checkpoint 恢复（第 {retry_count + 1} 次）"
        else:
            message = f"执行恢复策略: {action.value}（第 {retry_count + 1} 次）"

        # 重置检测器统计
        self.detector.reset_task(task_id)

        result = RecoveryResult(
            success=True,
            action=action,
            message=message,
        )
        self._recovery_history[task_id].append(result)
        return result

    def get_recovery_history(self, task_id: str) -> List[RecoveryResult]:
        """获取任务的恢复历史"""
        return list(self._recovery_history.get(task_id, []))

    def reset_recovery(self, task_id: str) -> None:
        """重置恢复历史"""
        self._recovery_history.pop(task_id, None)

    # ── Internal ────────────────────────────────────────────────

    def _select_recovery_action(self, decision: LoopDecision) -> RecoveryAction:
        """根据循环决策选择合适的恢复动作"""
        reason = decision.reason

        if "总迭代" in reason:
            return RecoveryAction.RETRY_WITH_BACKOFF
        elif "序列" in reason:
            return RecoveryAction.CONTINUE_FROM_CHECKPOINT
        elif "节点" in reason and "访问" in reason:
            return RecoveryAction.ALTERNATIVE_PATH
        else:
            return RecoveryAction.CONTINUE_FROM_CHECKPOINT

    def _calculate_backoff(self, retry_count: int) -> float:
        """计算指数退避时间"""
        base = self.detector.config.recovery_backoff_base
        return base ** (retry_count + 1)
