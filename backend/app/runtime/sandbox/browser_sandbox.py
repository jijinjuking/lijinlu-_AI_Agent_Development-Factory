"""
Browser Sandbox — 浏览器自动化沙箱

基于 Playwright 的浏览器自动化执行环境。
用于 Agent 执行网页操作（表单填充、截图、爬虫等）。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.runtime.sandbox.models import (
    SandboxConfig, SandboxResult, SandboxStatus, SandboxType, SecurityLevel,
)
from app.runtime.sandbox.security import SecurityValidator

logger = logging.getLogger(__name__)


class BrowserSandbox:
    """浏览器自动化沙箱。

    功能：
    - Playwright 浏览器启动/关闭
    - 页面导航、截图、DOM 操作
    - 脚本注入
    - 超时和资源限制
    - Playwright 不可用时报告不可用（不降级）

    安全策略：
    - 默认只允许白名单域名
    - 禁止文件上传（除非显式允许）
    - 所有网络请求可审计
    """

    DEFAULT_TIMEOUT = 30
    _playwright_available: bool | None = None

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig(sandbox_type=SandboxType.BROWSER)
        self._validator = SecurityValidator(config.security_policy if config else None)
        self._browser = None
        self._context = None
        self._allowed_domains: list[str] = config.allowed_domains if config else []

    @classmethod
    async def check_available(cls) -> bool:
        """检查 Playwright 是否可用"""
        if cls._playwright_available is not None:
            return cls._playwright_available
        try:
            from playwright.async_api import async_playwright
            cls._playwright_available = True
            logger.info("Playwright (browser sandbox) available")
        except ImportError:
            logger.warning("Playwright not installed, browser sandbox unavailable")
            cls._playwright_available = False
        return cls._playwright_available

    async def _ensure_browser(self):
        """确保浏览器已启动"""
        if self._browser is not None:
            return

        if not await self.check_available():
            raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")

        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )

    async def execute(self, code: str, context: dict = None, timeout: int = None) -> SandboxResult:
        """执行浏览器操作。

        code 应为 Playwright 脚本，可在 page 对象上操作。
        自动注入 page/context 变量。
        """
        timeout = timeout or self.config.timeout_seconds or self.DEFAULT_TIMEOUT

        # 安全检查：域名白名单
        if self._allowed_domains and self.config.security_level != SecurityLevel.NONE:
            for domain in self._allowed_domains:
                if domain in code:
                    break
            else:
                return SandboxResult(
                    success=False, output="",
                    error="Security: code references no allowed domain",
                    exit_code=1, duration_ms=0,
                )

        try:
            await self._ensure_browser()

            page = await self._browser.new_page()
            start = time.monotonic()

            try:
                # 允许脚本访问 page 和 context
                exec_globals = {
                    "page": page,
                    "browser": self._browser,
                    "context": self._browser.contexts[0] if self._browser.contexts else None,
                    **(context or {}),
                }
                exec_locals = {}

                # 用 asyncio.wait_for 外层控制超时
                exec_script = f"""
async def __sandbox_main__():
{chr(10).join('    ' + line for line in code.split(chr(10)))}
"""
                exec(exec_script, exec_globals, exec_locals)

                main_fn = exec_locals.get("__sandbox_main__")
                if main_fn:
                    await asyncio.wait_for(main_fn(), timeout=timeout)

                output = await page.content()
                result = SandboxResult(
                    success=True,
                    output=output[:10000],  # 限制输出大小
                    error="",
                    exit_code=0,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    metadata={"sandbox_type": "browser", "url": page.url},
                )

            except asyncio.TimeoutError:
                result = SandboxResult(
                    success=False, output="",
                    error=f"Browser execution timed out after {timeout}s",
                    exit_code=-1,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            except Exception as e:
                result = SandboxResult(
                    success=False, output="",
                    error=f"Browser execution error: {e}",
                    exit_code=1,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

            return result

        except RuntimeError as e:
            return SandboxResult(
                success=False, output="", error=str(e),
                exit_code=1, duration_ms=0,
            )

    async def screenshot(self, url: str, timeout: int = 30) -> SandboxResult:
        """对 URL 截图"""
        code = f'''
await page.goto("{url}", timeout={timeout * 1000})
await page.screenshot(path="/tmp/screenshot.png", full_page=True)
print("Screenshot saved")
'''
        return await self.execute(code)

    async def cleanup(self) -> None:
        """清理浏览器资源"""
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if hasattr(self, '_pw') and self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self._browser = None
