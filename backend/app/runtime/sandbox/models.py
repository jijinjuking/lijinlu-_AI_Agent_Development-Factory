"""Sandbox System — 数据模型"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class SandboxType(str, Enum):
    """沙箱类型"""
    PYTHON = "python"       # Python 代码执行
    DOCKER = "docker"       # Docker 容器
    BROWSER = "browser"     # 浏览器沙箱（Playwright）
    TOOL = "tool"           # Tool 执行隔离
    SKILL = "skill"         # Skill 插件执行


class SandboxStatus(str, Enum):
    """沙箱状态"""
    CREATING = "creating"
    RUNNING = "running"
    EXECUTING = "executing"
    IDLE = "idle"
    ERROR = "error"
    DESTROYED = "destroyed"


class SecurityLevel(str, Enum):
    """安全等级"""
    NONE = "none"          # 无限制（仅 trusted 代码）
    LOW = "low"            # 基本限制（CPU + 内存）
    MEDIUM = "medium"      # 标准隔离 + 网络白名单
    HIGH = "high"          # 严格隔离 + 无网络 + 只读 FS


@dataclass
class SecurityPolicy:
    """安全策略配置"""
    level: SecurityLevel = SecurityLevel.MEDIUM
    # 命令白名单（Docker/Tool sandbox）
    allowed_commands: set[str] = field(default_factory=lambda: {
        "python", "pip", "node", "npm", "git", "curl", "wget", "ls", "cat", "echo"
    })
    # 禁止的命令
    blocked_commands: set[str] = field(default_factory=lambda: {
        "rm -rf /", "shutdown", "reboot", "mkfs", "dd", "chmod 777 /"
    })
    # 网络限制
    allow_network: bool = True
    allowed_hosts: list[str] = field(default_factory=list)  # 空 = 全部允许
    blocked_hosts: list[str] = field(default_factory=lambda: ["169.254.169.254"])  # 云元数据
    # 文件系统限制
    read_only: bool = False
    allowed_paths: list[str] = field(default_factory=list)   # 空 = 全部允许
    blocked_paths: list[str] = field(default_factory=lambda: [
        "/etc/passwd", "/etc/shadow", "/root/.ssh",
        "~/.ssh", "~/.aws", "~/.config", "C:\\Windows"
    ])
    # 资源限制
    max_memory_mb: int = 512
    max_cpu_percent: int = 50
    max_execution_time_sec: int = 300
    max_disk_mb: int = 1024
    # Python 特有
    python_allow_imports: list[str] = field(default_factory=list)  # 空 = 安全内置
    python_blocked_modules: set[str] = field(default_factory=lambda: {
        "os", "subprocess", "shutil", "sys", "socket",
        "ctypes", "multiprocessing", "signal", "importlib"
    })


@dataclass
class SandboxConfig:
    """沙箱创建配置"""
    sandbox_type: SandboxType = SandboxType.PYTHON
    task_id: str = ""
    security: SecurityPolicy = field(default_factory=SecurityPolicy)
    # 超额配置
    labels: dict[str, str] = field(default_factory=dict)
    extra_env: dict[str, str] = field(default_factory=dict)
    # Docker/Browser 配置
    network_disabled: bool = True
    memory_limit_mb: int = 256
    cpu_limit: float = 1.0
    readonly_fs: bool = True
    allowed_domains: list[str] = field(default_factory=list)
    timeout_seconds: int = 30


@dataclass
class SandboxResult:
    """沙箱执行结果"""
    success: bool
    output: str = ""
    error: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0
    memory_used_mb: float = 0.0
    sandbox_id: str = ""
    task_id: str = ""

    @property
    def truncated(self) -> bool:
        return len(self.output) > 100_000 or len(self.error) > 100_000


@dataclass
class SandboxInfo:
    """沙箱元数据"""
    sandbox_id: str
    sandbox_type: SandboxType
    status: SandboxStatus
    task_id: str
    created_at: str = ""
    last_used_at: str = ""
    execution_count: int = 0
    total_duration_ms: float = 0.0
    config: Optional[SandboxConfig] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.last_used_at:
            self.last_used_at = self.created_at
