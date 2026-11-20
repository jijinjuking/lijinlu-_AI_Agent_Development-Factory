"""
AI Runtime OS — 数据库引擎（SQLAlchemy async）
开发默认用 SQLite，生产切换到 PostgreSQL
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    # aiosqlite 异步驱动不需要 check_same_thread（仅同步 sqlite 需要）
    connect_args={} if settings.is_sqlite else {},
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI 依赖注入：每次请求提供数据库会话"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """创建所有表（开发用，生产用 Alembic 迁移）"""
    # 确保所有模型已注册到 Base.metadata
    import app.models.agent  # noqa: F401
    import app.models.project  # noqa: F401  # Project 在 Issue 之前
    import app.models.issue  # noqa: F401   # Issue 在 Task 之前（Task 引用 Issue）
    import app.models.comment  # noqa: F401 # Comment 引用 Issue
    import app.models.issue_attachment  # noqa: F401
    import app.models.user  # noqa: F401   # User 在 Task/Tenant 之前
    import app.models.task  # noqa: F401
    import app.models.event  # noqa: F401
    import app.models.pipeline  # noqa: F401
    import app.models.artifact  # noqa: F401
    import app.models.skill  # noqa: F401
    import app.models.memory  # noqa: F401
    import app.models.settings  # noqa: F401
    import app.models.tool  # noqa: F401
    import app.models.context  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_db)


def _migrate_db(conn) -> None:
    """开发环境自动迁移：为已有表添加缺失列（无 Alembic 时的折中方案）"""
    import sqlalchemy as sa

    inspector = sa.inspect(conn)
    # (table, column_name, column_type_sql, default_value)
    migrations: list[tuple[str, str, str, str]] = [
        ("agents", "model_mode", "VARCHAR(16)", "'bound'"),
        ("agents", "system_prompt", "TEXT", "NULL"),
        ("tasks", "issue_id", "UUID", "NULL"),
        ("tasks", "parent_task_id", "UUID", "NULL"),
    ]

    for table, col_name, col_type, default_val in migrations:
        if table not in inspector.get_table_names():
            continue
        existing_cols = [c["name"] for c in inspector.get_columns(table)]
        if col_name not in existing_cols:
            if default_val == "NULL":
                conn.execute(
                    sa.text(
                        f"ALTER TABLE {table} ADD COLUMN {col_name} "
                        f"{col_type}"
                    )
                )
            else:
                conn.execute(
                    sa.text(
                        f"ALTER TABLE {table} ADD COLUMN {col_name} "
                        f"{col_type} NOT NULL DEFAULT {default_val}"
                    )
                )
