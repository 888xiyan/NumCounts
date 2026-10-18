from functools import lru_cache
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExternalExecutorSettings(BaseModel):
    """A trusted executor configuration loaded only from deployment settings."""

    model_config = ConfigDict(extra="forbid")

    executor_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    base_url: str
    execution_path: str = "/v1/executions"
    authorization_token: str | None = None
    timeout_ms: int = Field(default=5000, ge=100, le=60000)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute http or https URL")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url cannot include query or fragment components")
        return value.rstrip("/")

    @field_validator("execution_path")
    @classmethod
    def validate_execution_path(cls, value: str) -> str:
        if not value.startswith("/") or "?" in value or "#" in value:
            raise ValueError("execution_path must be an absolute path without query")
        return value


class Settings(BaseSettings):
    app_name: str = "NumCounts"
    app_env: str = "development"
    app_debug: bool = False
    api_v1_prefix: str = "/api/v1"
    database_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 20
    log_level: str = "INFO"
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    seed_admin_username: str = "admin"
    seed_admin_password: str
    seed_user_username: str = "user"
    seed_user_password: str
    runner_poll_interval_seconds: float = 1.0
    runner_batch_size: int = 100
    external_executors: list[ExternalExecutorSettings] = Field(default_factory=list)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
