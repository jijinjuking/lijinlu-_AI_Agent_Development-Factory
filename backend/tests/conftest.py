"""
Pytest 配置 + 共享 Fixtures
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# =============================================================================
# 临时数据库文件（整个 test session 共享）
# =============================================================================
# 不能用 :memory:，因为 SQLite 每个连接独立 DB，导致 db_session fixture
# 看不到 test_engine fixture 创建的表。用临时文件解决这个问题。
_tmp_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEST_DB_PATH = _tmp_db_file.name
_tmp_db_file.close()

# 整个 session 用同一个临时文件
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"

# Override DB to use the temp file
from app.config import settings
settings.database_url = TEST_DB_URL
settings.debug = True

# 确保所有模型已注册到 Base.metadata（create_all 需要）
import app.models.agent  # noqa: F401
import app.models.task  # noqa: F401
import app.models.event  # noqa: F401
import app.models.pipeline  # noqa: F401
import app.models.artifact  # noqa: F401
import app.models.skill  # noqa: F401
import app.models.memory  # noqa: F401
import app.models.settings  # noqa: F401
import app.models.tool  # noqa: F401
import app.models.context  # noqa: F401
import app.models.evaluation  # noqa: F401

from app.main import app
from app.database import Base, get_db, async_session_factory


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """测试用临时文件数据库引擎"""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()
    # 清理临时文件
    try:
        os.unlink(TEST_DB_PATH)
    except OSError:
        pass


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """每个测试函数独立的 DB session（外层事务回滚，保证测试隔离）"""
    async with test_engine.connect() as conn:
        async with conn.begin() as outer_trans:
            session_factory = async_sessionmaker(
                bind=conn, class_=AsyncSession, expire_on_commit=False,
            )
            async with session_factory() as session:
                yield session
            await outer_trans.rollback()


# =============================================================================
# Auth Override for Tests
# =============================================================================
# 所有依赖 get_current_user 的 API 测试需要认证。
# 此处 override get_current_user，返回一个不访问 DB 的 mock 对象。
# =============================================================================
from app.api.auth import get_current_user as _real_get_current_user
from app.models.user import User as _UserORM

# 创建一个内存中的 mock user（非 ORM，避免 detached session 问题）
_mock_user = _UserORM()
_mock_user.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
_mock_user.username = "testuser"
_mock_user.email = "test@example.com"
_mock_user.password_hash = "fake"
_mock_user.role = "admin"
_mock_user.is_active = True
_mock_user.display_name = "Test User"
_mock_user.created_at = None
_mock_user.updated_at = None
_mock_user.last_login_at = None
_mock_user.tenant_id = None
_mock_user.refresh_token_hash = None

async def _mock_get_current_user():
    """Mock get_current_user —— 直接返回内存中的 mock user，不访问 DB"""
    return _mock_user

# 立即注册 override（模块加载时执行，早于任何测试）
app.dependency_overrides[_real_get_current_user] = _mock_get_current_user


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP 测试客户端"""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/api/v1") as ac:
        yield ac
    # 只清除 get_db override，保留 auth override
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def sample_agent(db_session: AsyncSession) -> str:
    """创建一个测试 Agent 并返回 ID（每次生成唯一名称，避免 UNIQUE 冲突）"""
    from app.models.agent import Agent
    aid = uuid.uuid4()
    unique_suffix = uuid.uuid4().hex[:8]
    agent = Agent(
        id=aid,
        name=f"Test-Agent-{unique_suffix}",
        role="developer",
        model="deepseek-chat",
        description="Test agent for unit tests",
        status="idle",
    )
    db_session.add(agent)
    await db_session.commit()
    return str(aid)


# ============================================================================
# W17: Planner Agent 集成 fixtures
# ============================================================================

@pytest_asyncio.fixture
async def kernel_with_planner(db_session: AsyncSession):
    """RuntimeKernel + PlannerAgent（模板模式，无 LLM）"""
    from app.runtime.state_manager import StateManager
    from app.runtime.checkpoint_manager import CheckpointManager
    from app.runtime.scheduler import Scheduler
    from app.runtime.policy_engine import PolicyEngine
    from app.runtime.model_router import ModelRouter
    from app.runtime.loop_detector import InfiniteLoopDetector
    from app.runtime.sandbox import SandboxManager
    from app.runtime.kernel import RuntimeKernel
    from app.runtime.planner import PlannerAgent, create_default_template_library

    kernel = RuntimeKernel(
        state_manager=StateManager(db_session),
        scheduler=Scheduler(),
        checkpoint_manager=CheckpointManager(db_session),
        policy_engine=PolicyEngine(),
        model_router=ModelRouter(),
        loop_detector=InfiniteLoopDetector(),
        sandbox_manager=SandboxManager(),
        planner_agent=PlannerAgent(
            template_library=create_default_template_library(),
            llm_service=None,
            min_template_score=0.1,
        ),
    )

    await kernel.start()
    yield kernel
    await kernel.stop()
