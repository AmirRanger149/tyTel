from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings shared by the bot and worker."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    bot_token: str = Field(default="", alias="BOT_TOKEN")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    database_path: Path = Field(default=Path("./data/tytel.db"), alias="DATABASE_PATH")
    temp_dir: Path = Field(default=Path("./data/tmp"), alias="TEMP_DIR")

    worker_concurrency: int = Field(default=2, ge=1, le=32, alias="WORKER_CONCURRENCY")
    user_rate_limit: int = Field(default=5, ge=1, alias="USER_RATE_LIMIT")
    group_rate_limit: int = Field(default=0, ge=0, alias="GROUP_RATE_LIMIT")
    max_duration_seconds: int = Field(default=600, ge=1, alias="MAX_DURATION_SECONDS")
    max_file_size_mb: int | None = Field(default=None, gt=0, alias="MAX_FILE_SIZE_MB")
    local_bot_api_url: str | None = Field(default=None, alias="LOCAL_BOT_API_URL")
    cookies_path: Path | None = Field(default=None, alias="COOKIES_PATH")
    proxy_url: str | None = Field(default=None, alias="PROXY_URL")
    dedup_lock_timeout_seconds: int = Field(
        default=1800, ge=30, alias="DEDUP_LOCK_TIMEOUT_SECONDS"
    )
    job_timeout_seconds: int = Field(default=1800, ge=60, alias="JOB_TIMEOUT_SECONDS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("local_bot_api_url", "proxy_url", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("cookies_path", "max_file_size_mb", mode="before")
    @classmethod
    def empty_optional_to_none(cls, value: object) -> object:
        return None if value in ("", None) else value

    @property
    def upload_limit_bytes(self) -> int:
        default_mb = 2000 if self.local_bot_api_url else 50
        return (self.max_file_size_mb or default_mb) * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
