"""
PermissionEngine — 基于角色的访问控制（RBAC）

职责:
- Role 定义：预设 admin/developer/viewer 三种角色
- 权限检查：资源 + 操作 匹配
- deny 优先：deny 权限覆盖 allow
- 角色优先级：高优先级角色覆盖低优先级
"""
from __future__ import annotations

from typing import Optional

from app.runtime.policy_engine.models import (
    Permission,
    PermissionAction,
    PermissionResource,
    Role,
    PolicyDecision,
    PolicyResult,
)


# ── 预设角色 ───────────────────────────────────────────

PRESET_ROLES: dict[str, Role] = {
    "admin": Role(
        name="admin",
        priority=100,
        permissions=[
            Permission(action=PermissionAction.READ, resource=resource, effect="allow")
            for resource in PermissionResource
        ] + [
            Permission(action=PermissionAction.WRITE, resource=resource, effect="allow")
            for resource in PermissionResource
        ] + [
            Permission(action=PermissionAction.EXECUTE, resource=resource, effect="allow")
            for resource in PermissionResource
        ] + [
            Permission(action=PermissionAction.DELETE, resource=resource, effect="allow")
            for resource in PermissionResource
        ] + [
            Permission(action=PermissionAction.MANAGE, resource=resource, effect="allow")
            for resource in PermissionResource
        ],
    ),
    "developer": Role(
        name="developer",
        priority=50,
        permissions=[
            Permission(action=PermissionAction.READ, resource=r, effect="allow")
            for r in [PermissionResource.AGENT, PermissionResource.TOOL,
                      PermissionResource.ARTIFACT, PermissionResource.TASK,
                      PermissionResource.WORKFLOW]
        ] + [
            Permission(action=PermissionAction.WRITE, resource=r, effect="allow")
            for r in [PermissionResource.AGENT, PermissionResource.TOOL,
                      PermissionResource.ARTIFACT, PermissionResource.TASK,
                      PermissionResource.WORKFLOW]
        ] + [
            Permission(action=PermissionAction.EXECUTE, resource=r, effect="allow")
            for r in [PermissionResource.AGENT, PermissionResource.TOOL,
                      PermissionResource.TASK, PermissionResource.WORKFLOW]
        ] + [
            Permission(action=PermissionAction.DELETE, resource=r, effect="allow")
            for r in [PermissionResource.ARTIFACT, PermissionResource.TASK]
        ],
    ),
    "viewer": Role(
        name="viewer",
        priority=10,
        permissions=[
            Permission(action=PermissionAction.READ, resource=r, effect="allow")
            for r in PermissionResource
        ],
    ),
}


class PermissionEngine:
    """权限引擎"""

    def __init__(self, roles: dict[str, Role] | None = None):
        self._roles: dict[str, Role] = dict(roles or PRESET_ROLES)

    # ── 角色管理 ───────────────────────────────────────

    def add_role(self, role: Role):
        self._roles[role.name] = role

    def remove_role(self, role_name: str) -> bool:
        if role_name in ("admin", "developer", "viewer"):
            return False  # 不允许删除预设角色
        return self._roles.pop(role_name, None) is not None

    def get_role(self, role_name: str) -> Role | None:
        return self._roles.get(role_name)

    def list_roles(self) -> list[Role]:
        return sorted(self._roles.values(), key=lambda r: r.priority, reverse=True)

    # ── 权限检查 ───────────────────────────────────────

    def check(
        self,
        role_names: list[str],
        action: PermissionAction,
        resource: PermissionResource,
        resource_id: Optional[str] = None,
    ) -> PolicyResult:
        """
        检查指定角色是否拥有某操作的权限。

        规则:
        1. deny 优先：任一角色有匹配的 deny → 拒绝
        2. allow 覆盖：任一角色有匹配的 allow → 允许
        3. 角色优先级：按 priority 排序，高优先级先判断
        4. resource_id 精确匹配优先于通配（None）
        """
        # 获取所有有效角色，按优先级排序
        active_roles = sorted(
            [r for r in (self._roles.get(n) for n in role_names) if r is not None],
            key=lambda r: r.priority,
            reverse=True,
        )

        if not active_roles:
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason=f"角色 {role_names} 不存在或无权限",
                checks={"has_role": False},
            )

        # deny 优先检查
        for role in active_roles:
            for perm in role.permissions:
                if perm.effect != "deny":
                    continue
                if self._match_permission(perm, action, resource, resource_id):
                    return PolicyResult(
                        decision=PolicyDecision.DENY,
                        reason=f"角色 {role.name} 拒绝 {action.value} {resource.value}" +
                               (f":{resource_id}" if resource_id else ""),
                        checks={"has_role": True, "explicit_deny": True},
                    )

        # allow 检查
        for role in active_roles:
            for perm in role.permissions:
                if perm.effect != "allow":
                    continue
                if self._match_permission(perm, action, resource, resource_id):
                    return PolicyResult(
                        decision=PolicyDecision.ALLOW,
                        checks={"has_role": True, "matched_allow": True},
                    )

        # 无匹配权限 → deny
        return PolicyResult(
            decision=PolicyDecision.DENY,
            reason=f"无角色授权 {action.value} {resource.value}" +
                   (f":{resource_id}" if resource_id else ""),
            checks={"has_role": True, "no_matching_permission": True},
        )

    def can_execute_tool(self, role_names: list[str], tool_name: str) -> PolicyResult:
        """检查是否能执行某工具"""
        return self.check(role_names, PermissionAction.EXECUTE,
                          PermissionResource.TOOL, tool_name)

    def can_run_agent(self, role_names: list[str], agent_name: str) -> PolicyResult:
        """检查是否能运行某 Agent"""
        return self.check(role_names, PermissionAction.EXECUTE,
                          PermissionResource.AGENT, agent_name)

    # ── 内部 ───────────────────────────────────────────

    @staticmethod
    def _match_permission(
        perm: Permission,
        action: PermissionAction,
        resource: PermissionResource,
        resource_id: Optional[str],
    ) -> bool:
        """权限匹配：action 必须相同，resource 必须相同，resource_id 可精确或通配"""
        if perm.action != action:
            return False
        if perm.resource != resource:
            return False
        if perm.resource_id is None:
            return True  # 通配符，匹配所有
        if resource_id is None:
            return False  # 精确要求但传入 None，不匹配
        return perm.resource_id == resource_id
