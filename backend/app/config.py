"""
AI Runtime OS — 配置管理
支持 .env 文件 + 环境变量，开发默认用 SQLite
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 应用 ----
    app_name: str = "AI Runtime OS"
    version: str = "1.0.0"
    debug: bool = True
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173,http://localhost:5174,http://localhost:5175,http://localhost:5176,http://localhost:5177,http://localhost:5178,tauri://localhost"

    # ---- 数据库 ----
    database_url: str = "sqlite+aiosqlite:///ai_runtime.db"

    # ---- LLM ----
    openai_api_key: str = ""
    openai_base_url: str = ""          # 留空则用 OpenAI 官方；填 DeepSeek/其他兼容地址则走该服务
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    ollama_base_url: str = "http://localhost:11434"
    default_llm_provider: str = "openai"   # openai | anthropic | ollama | mock
    default_llm_model: str = "deepseek-chat"

    # ---- Redis ----
    redis_url: str = "redis://localhost:6379/0"

    # ---- Auth / JWT ----
    secret_key: str = "dev-secret-key-change-in-production!"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7   # 7 天
    refresh_token_expire_days: int = 30

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
