"""
AI Runtime OS — 系统设置模型（LLM 配置 / API Key / 权限）
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class ModelConfig(Base, UUIDPrimaryKey, TimestampMixin):
    """LLM 模型配置"""
    __tablename__ = "model_configs"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), default="")
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="openai",
        comment="openai | anthropic | ollama | custom",
    )
    endpoint: Mapped[str] = mapped_column(String(512), default="")  # 兼容旧字段
    api_base: Mapped[str] = mapped_column(String(512), default="")
    api_key_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    default_for: Mapped[str] = mapped_column(String(512), default="")
    max_tokens: Mapped[int] = mapped_column(Integer, default=128000)
    temperature: Mapped[float] = mapped_column(Float, default=0.4)
    cost_input_per_1k: Mapped[float] = mapped_column(Float, default=0.0)
    cost_output_per_1k: Mapped[float] = mapped_column(Float, default=0.0)
    api_key_configured: Mapped[bool] = mapped_column(Boolean, default=False)


class ApiKey(Base, UUIDPrimaryKey, TimestampMixin):
    """API Key 管理"""
    __tablename__ = "api_keys"

    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), default="")
    masked_key: Mapped[str] = mapped_column(String(64), default="")
    # 加密存储完整 key
    encrypted_key: Mapped[str] = mapped_column(String(512), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AgentPermission(Base, UUIDPrimaryKey, TimestampMixin):
    """Agent 角色权限"""
    __tablename__ = "agent_permissions"

    role_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    role_name: Mapped[str] = mapped_column(String(64), nullable=False)
    can_create_pipeline: Mapped[bool] = mapped_column(Boolean, default=False)
    can_deploy: Mapped[bool] = mapped_column(Boolean, default=False)
    can_access_network: Mapped[bool] = mapped_column(Boolean, default=True)
    can_write_files: Mapped[bool] = mapped_column(Boolean, default=True)
    can_execute_commands: Mapped[bool] = mapped_column(Boolean, default=False)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=2)
    max_tokens_per_task: Mapped[int] = mapped_column(Integer, default=30000)
    max_daily_cost: Mapped[float] = mapped_column(Float, default=10.0)


class RuntimeSetting(Base, UUIDPrimaryKey, TimestampMixin):
    """运行时配置（key-value 单例表）"""
    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="配置键")
    value: Mapped[str] = mapped_column(String(512), default="", comment="配置值（JSON 字符串）")
    description: Mapped[str] = mapped_column(String(255), default="", comment="配置说明")
