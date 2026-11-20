"""Agent 角色提示词模块。

每个角色有预置的「默认提示词」，Agent 可通过 system_prompt 字段覆盖。
提示词分两层：
1. SYSTEM — 角色定义、工作方法论、约束条件（注入到 messages[0]）
2. TASK — 任务执行指令（由 agent_executor 附加到 messages[1]）
"""

from app.prompts.roles import (
    ROLE_PROMPTS,
    get_role_prompt,
    get_effective_prompt,
)

__all__ = [
    "ROLE_PROMPTS",
    "get_role_prompt",
    "get_effective_prompt",
]
