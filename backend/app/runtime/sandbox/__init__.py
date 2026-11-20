"""Sandbox System (W12)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Agent 隔离执行环境。

组件:
- SandboxManager: 沙箱生命周期管理（创建/获取/销毁/池化）
- PythonSandbox: Python 代码隔离执行（子进程 + 安全验证 + 超时）
- DockerSandbox: Docker 容器隔离执行（容器 + 资源限制 + 网络隔离）
- BrowserSandbox: 浏览器自动化沙箱（Playwright + 页面操作 + 截图）
- SecurityValidator: 安全策略执行（命令白名单 + 代码检查 + 路径验证）
- SecurityPolicy: 安全策略配置（4 级安全等级）
"""

from app.runtime.sandbox.models import (
    SandboxType,
    SandboxStatus,
    SecurityLevel,
    SecurityPolicy,
    SandboxConfig,
    SandboxResult,
    SandboxInfo,
)
from app.runtime.sandbox.security import SecurityValidator
from app.runtime.sandbox.python_sandbox import PythonSandbox
from app.runtime.sandbox.docker_sandbox import DockerSandbox
from app.runtime.sandbox.browser_sandbox import BrowserSandbox
from app.runtime.sandbox.sandbox_manager import SandboxManager

__all__ = [
    "SandboxManager",
    "PythonSandbox",
    "DockerSandbox",
    "BrowserSandbox",
    "SecurityValidator",
    "SandboxType",
    "SandboxStatus",
    "SecurityLevel",
    "SecurityPolicy",
    "SandboxConfig",
    "SandboxResult",
    "SandboxInfo",
]
