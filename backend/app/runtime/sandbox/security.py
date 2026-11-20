"""Sandbox — 安全策略执行引擎"""

import re
from app.runtime.sandbox.models import SecurityPolicy, SecurityLevel


class SecurityValidator:
    """对代码/命令进行安全验证"""

    def __init__(self, policy: SecurityPolicy = None):
        self.policy = policy or SecurityPolicy()

    # ── 命令安全检查 ──

    def validate_command(self, command: str) -> tuple[bool, str]:
        """检查 shell 命令是否被允许。
        返回 (allowed, reason)。
        """
        cmd_lower = command.strip().lower()

        # 1. 检查禁止命令（blocklist 优先）
        for blocked in self.policy.blocked_commands:
            if blocked.lower() in cmd_lower:
                return False, f"Blocked command pattern: {blocked}"

        # 2. 检查白名单
        cmd_base = cmd_lower.split()[0] if cmd_lower else ""
        if cmd_base and cmd_base not in {c.lower() for c in self.policy.allowed_commands}:
            return False, f"Command not allowed: {cmd_base}"

        # 3. HIGH 安全等级禁止一切网络相关命令
        if self.policy.level == SecurityLevel.HIGH:
            for net_cmd in ("curl", "wget", "ping", "nc", "telnet", "ssh", "ftp"):
                if net_cmd in cmd_lower:
                    return False, f"Network command blocked at HIGH security: {net_cmd}"

        return True, "OK"

    # ── 网络访问检查 ──

    def validate_network(self, host: str) -> tuple[bool, str]:
        """检查网络访问是否被允许"""
        if not self.policy.allow_network:
            return False, "Network access disabled"

        for blocked in self.policy.blocked_hosts:
            if blocked in host:
                return False, f"Blocked host: {host}"

        if self.policy.allowed_hosts and host not in self.policy.allowed_hosts:
            return False, f"Host not in allowlist: {host}"

        return True, "OK"

    # ── 文件系统检查 ──

    def validate_path(self, path: str, write: bool = False) -> tuple[bool, str]:
        """检查文件路径访问权限"""
        norm = path.replace("\\", "/")

        for blocked in self.policy.blocked_paths:
            b_norm = blocked.replace("\\", "/")
            if b_norm in norm:
                return False, f"Blocked path: {path}"

        if write and self.policy.read_only:
            return False, "Filesystem is read-only"

        if self.policy.allowed_paths:
            if not any(ap.replace("\\", "/") in norm for ap in self.policy.allowed_paths):
                return False, f"Path not in allowlist: {path}"

        return True, "OK"

    # ── Python 导入检查 ──

    def validate_import(self, module: str) -> tuple[bool, str]:
        """检查 Python 模块导入是否被允许"""
        if module in self.policy.python_blocked_modules:
            return False, f"Blocked module: {module}"

        if self.policy.python_allow_imports and module not in self.policy.python_allow_imports:
            return False, f"Module not in allowlist: {module}"

        return True, "OK"

    # ── Python 代码静态检查 ──

    def validate_python_code(self, code: str) -> tuple[bool, str]:
        """对 Python 代码进行静态安全检查"""
        # 检查危险模式
        dangerous_patterns = [
            (r'import\s+os\b', "os module import"),
            (r'import\s+subprocess\b', "subprocess module import"),
            (r'import\s+shutil\b', "shutil module import"),
            (r'import\s+ctypes\b', "ctypes module import"),
            (r'import\s+socket\b', "socket module import"),
            (r'from\s+os\s+import', "os module import"),
            (r'from\s+subprocess\s+import', "subprocess module import"),
            (r'__import__\s*\(', "dynamic import"),
            (r'eval\s*\(', "eval() call"),
            (r'exec\s*\(', "exec() call"),
            (r'compile\s*\(', "compile() call"),
            (r'open\s*\(\s*[\'"]/[^/]', "open absolute path"),
            (r'open\s*\(\s*[\'"]C:', "open Windows absolute path"),
        ]

        for pattern, desc in dangerous_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                # LOW 安全级别只警告，不阻止
                if self.policy.level == SecurityLevel.LOW:
                    continue
                return False, f"Dangerous pattern: {desc}"

        return True, "OK"

    # ── 资源限制检查 ──

    def validate_resources(self, code_size: int) -> tuple[bool, str]:
        """检查代码大小是否在资源限制内"""
        max_bytes = self.policy.max_memory_mb * 1024 * 1024
        if code_size > max_bytes:
            return False, f"Code size {code_size} bytes exceeds limit {max_bytes} bytes"
        return True, "OK"
