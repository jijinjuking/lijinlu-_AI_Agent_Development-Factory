"""
轻量 State 数据结构 — Phase 1 W3
原则4：State 只存引用，不存内容。内容走 Artifact Store。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class LightweightState:
    """LangGraph 全局共享 State。只存引用，不存内容。"""

    # ── 任务标识 ──
    task_id: str = ""
    project_id: str = ""

    # ── 流程控制 ──
    current_node: str = ""
    workflow_status: str = "idle"  # idle | running | paused | waiting_approval
    error_count: int = 0
    max_retries: int = 3

    # ── 引用（核心！内容不在这里） ──
    artifact_refs: list[str] = field(default_factory=list)
    context_refs: list[str] = field(default_factory=list)
    checkpoint_id: str | None = None

    # ── 人工干预 ──
    approval_needed: bool = False
    approval_result: bool | None = None

    # ── 最近消息（只保留最近 N 条） ──
    messages: list[dict[str, Any]] = field(default_factory=list)
    current_goal: str = ""

    # ── 可观测元数据 ──
    metadata: dict[str, Any] = field(default_factory=dict)

    # ── 步骤历史（用于看板展示） ──
    steps: list[dict[str, Any]] = field(default_factory=list)

    MAX_MESSAGES = 50

    def add_message(self, role: str, content: str) -> None:
        """追加消息，自动截断保留最近 N 条"""
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > self.MAX_MESSAGES:
            self.messages = self.messages[-self.MAX_MESSAGES:]

    def add_artifact_ref(self, artifact_id: str) -> None:
        if artifact_id not in self.artifact_refs:
            self.artifact_refs.append(artifact_id)

    def add_step(self, node: str, outcome: str, detail: str = "") -> None:
        self.steps.append({
            "node": node,
            "outcome": outcome,
            "detail": detail,
        })

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LightweightState":
        # 过滤掉未知字段
        known = {f.name for f in cls.__dataclass_fields__.values()}
        cleaned = {k: v for k, v in data.items() if k in known}
        return cls(**cleaned)

    @classmethod
    def create_for_task(cls, task_id: str, goal: str = "", project_id: str = "") -> "LightweightState":
        return cls(
            task_id=task_id,
            project_id=project_id,
            current_goal=goal,
            workflow_status="idle",
        )
