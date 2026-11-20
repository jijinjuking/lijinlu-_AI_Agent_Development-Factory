"""
Interrupt Handler — 人机交互中断管理

处理 LangGraph 执行过程中的中断：
- request_approval: 创建中断请求
- resume_with_approval: 恢复执行（批准/拒绝）
- get_pending_interrupts: 查询待处理中断

中断状态存储在 LightweightState 中（approval_needed / approval_result 字段），
不引入外部依赖。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("ai_runtime_os.interrupt_handler")


@dataclass
class InterruptRequest:
    """中断请求数据结构"""
    task_id: str
    node_id: str
    message: str = ""
    timeout_seconds: int = 300
    created_at: str = ""
    status: str = "pending"  # pending | approved | rejected | timeout

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "node_id": self.node_id,
            "message": self.message,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InterruptRequest":
        return cls(
            task_id=data.get("task_id", ""),
            node_id=data.get("node_id", ""),
            message=data.get("message", ""),
            timeout_seconds=data.get("timeout_seconds", 300),
            created_at=data.get("created_at", ""),
            status=data.get("status", "pending"),
        )


class InterruptHandler:
    """
    中断处理器 — Phase 1 内存实现。

    管理所有待处理的中断请求：
    - 执行到 human_approval 节点时创建中断
    - 用户批准/拒绝后恢复执行

    Phase 2 可迁移到 Redis 或数据库存储。
    """

    def __init__(self):
        # task_id → interrupt_request
        self._pending: dict[str, InterruptRequest] = {}
        # task_id → list of resolved requests (for audit trail)
        self._history: dict[str, list[InterruptRequest]] = {}

    # ── 创建中断 ──

    def request_approval(
        self,
        task_id: str,
        node_id: str,
        message: str = "",
        timeout_seconds: int = 300,
    ) -> InterruptRequest:
        """
        为指定任务创建中断请求。

        Args:
            task_id: 任务 ID
            node_id: 触发中断的节点 ID
            message: 中断消息（展示给用户）
            timeout_seconds: 超时时间（秒），超时未处理则自动拒绝

        Returns:
            InterruptRequest 对象
        """
        if task_id in self._pending:
            logger.warning("Task %s already has a pending interrupt, overwriting", task_id)

        req = InterruptRequest(
            task_id=task_id,
            node_id=node_id,
            message=message,
            timeout_seconds=timeout_seconds,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="pending",
        )
        self._pending[task_id] = req

        logger.info("Interrupt created: task=%s node=%s message=%s", task_id, node_id, message[:50])
        return req

    # ── 恢复执行 ──

    def resume_with_approval(
        self,
        task_id: str,
        approved: bool,
        reason: str = "",
    ) -> Optional[InterruptRequest]:
        """
        批准或拒绝中断请求，恢复任务执行。

        Args:
            task_id: 任务 ID
            approved: True = 批准继续, False = 拒绝
            reason: 审批意见

        Returns:
            已处理的 InterruptRequest，若无挂起中断则返回 None
        """
        if task_id not in self._pending:
            logger.warning("No pending interrupt for task %s", task_id)
            return None

        req = self._pending.pop(task_id)
        req.status = "approved" if approved else "rejected"
        self._history.setdefault(task_id, []).append(req)

        logger.info(
            "Interrupt resolved: task=%s approved=%s reason=%s",
            task_id, approved, reason[:50] if reason else "(none)",
        )
        return req

    # ── 查询 ──

    def get_pending(self, task_id: str) -> Optional[InterruptRequest]:
        """获取任务的挂起中断（不修改状态）"""
        return self._pending.get(task_id)

    def has_pending(self, task_id: str) -> bool:
        """检查任务是否有挂起中断"""
        return task_id in self._pending

    def list_all_pending(self) -> list[InterruptRequest]:
        """列出所有挂起的中断"""
        return list(self._pending.values())

    def get_history(self, task_id: str) -> list[InterruptRequest]:
        """获取任务的所有历史中断记录"""
        return self._history.get(task_id, [])

    def cancel(self, task_id: str) -> Optional[InterruptRequest]:
        """取消中断请求（不影响任务状态）"""
        if task_id not in self._pending:
            return None
        req = self._pending.pop(task_id)
        req.status = "timeout"
        self._history.setdefault(task_id, []).append(req)
        logger.info("Interrupt cancelled: task=%s", task_id)
        return req


# ═══════════════════════════════════════════
# 全局默认实例
# ═══════════════════════════════════════════

interrupt_handler = InterruptHandler()
