"""
State Validator — 防止 State 膨胀
原则4：State 只存引用，内容走 Artifact Store。
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("ai_runtime_os.state_validator")

# 100KB 阈值 — 超过则拒绝保存，强制将内容移到 Artifact Store
STATE_SIZE_LIMIT_BYTES = 100_000


class StateTooLargeError(ValueError):
    """State 超过大小限制"""

    def __init__(self, size_bytes: int, limit_bytes: int = STATE_SIZE_LIMIT_BYTES):
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            f"State 大小 {size_bytes} bytes 超过限制 {limit_bytes} bytes。"
            f"请将内容移到 Artifact Store，State 只保留 artifact_refs 引用。"
        )


class StateValidationWarning:
    """非致命警告"""

    def __init__(self, field: str, message: str, current_size: int):
        self.field = field
        self.message = message
        self.current_size = current_size


class StateValidator:
    """验证 State 是否符合轻量化原则"""

    @staticmethod
    def validate(state_dict: dict[str, Any]) -> list[StateValidationWarning]:
        """
        验证 State，返回警告列表。
        如果 State 超过限制则直接抛出 StateTooLargeError。
        """
        warnings: list[StateValidationWarning] = []
        state_json = json.dumps(state_dict, ensure_ascii=False, default=str)
        size = len(state_json.encode("utf-8"))

        # ── 硬限制：超过 100KB 直接拒绝 ──
        if size > STATE_SIZE_LIMIT_BYTES:
            raise StateTooLargeError(size)

        # ── 软警告 ──
        if size > 10_000:  # 10KB
            warnings.append(StateValidationWarning(
                field="__state__",
                message=f"State 大小 {size} bytes，建议检查是否有大内容未移入 Artifact Store",
                current_size=size,
            ))

        # 检查 messages 是否过多
        messages = state_dict.get("messages", [])
        if len(messages) > 100:
            warnings.append(StateValidationWarning(
                field="messages",
                message=f"消息数 {len(messages)}，建议只保留最近 {50} 条",
                current_size=len(messages),
            ))

        # 检查 artifact_refs 是否过大（单条 ID 应很短）
        artifact_refs = state_dict.get("artifact_refs", [])
        if len(artifact_refs) > 1000:
            warnings.append(StateValidationWarning(
                field="artifact_refs",
                message=f"Artifact 引用数 {len(artifact_refs)}，建议归档旧引用",
                current_size=len(artifact_refs),
            ))

        for key, value in state_dict.items():
            if isinstance(value, str) and len(value) > 50_000:
                warnings.append(StateValidationWarning(
                    field=key,
                    message=f"字段 '{key}' 包含 {len(value)} 字符的大文本，"
                            f"建议移入 Artifact Store",
                    current_size=len(value),
                ))

        return warnings

    @staticmethod
    def get_size(state_dict: dict[str, Any]) -> int:
        """获取 State 序列化后的字节大小"""
        return len(json.dumps(state_dict, ensure_ascii=False, default=str).encode("utf-8"))
