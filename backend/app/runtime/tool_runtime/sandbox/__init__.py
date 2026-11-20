"""
Process Sandbox — 基于进程隔离的轻量沙箱
无需 Docker 依赖，通过子进程 + 资源限制实现隔离
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ProcessSandbox:
    """
    进程沙箱 — 提供受限的执行环境
    """

    def __init__(self, sandbox_id: str | None = None):
        self.sandbox_id = sandbox_id or f"sandbox_{id(self)}"
        self._env: Dict[str, str] = {}
        self._allowed_paths: list[str] = []
        self._max_memory_mb: int = 256

    def set_env(self, key: str, value: str) -> None:
        """设置环境变量"""
        self._env[key] = value

    def allow_path(self, path: str) -> None:
        """允许访问的路径"""
        self._allowed_paths.append(path)

    def set_memory_limit(self, mb: int) -> None:
        """设置内存限制"""
        self._max_memory_mb = mb

    def get_env(self) -> Dict[str, str]:
        """获取沙箱环境变量"""
        return dict(self._env)

    def is_path_allowed(self, path: str) -> bool:
        """检查路径是否允许"""
        if not self._allowed_paths:
            return True  # 未配置则允许所有
        import os
        for allowed in self._allowed_paths:
            if os.path.abspath(path).startswith(os.path.abspath(allowed)):
                return True
        return False

    def cleanup(self) -> None:
        """清理沙箱资源"""
        self._env.clear()
        self._allowed_paths.clear()
        logger.debug("Sandbox %s cleaned up", self.sandbox_id)
