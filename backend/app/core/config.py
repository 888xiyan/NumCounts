import hashlib
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExternalFunctionArtifact(BaseModel):
    """An audited source bundle for one external function version.

    The source is supplied only in deployment configuration, never by a
    calculation record.  The digest makes configuration mistakes observable
    before an external function can be used for a formal calculation.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    language: Literal["python"] = "python"
    source: str = Field(min_length=1, max_length=64 * 1024)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dependencies: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def verify_source_digest(self) -> "ExternalFunctionArtifact":
        actual_digest = hashlib.sha256(self.source.encode()).hexdigest()
        if actual_digest != self.source_sha256:
            raise ValueError("source_sha256 does not match source")
        return self


class ExternalExecutorSettings(BaseModel):
    """A trusted executor configuration loaded only from deployment settings."""

    model_config = ConfigDict(extra="forbid")

    executor_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    base_url: str
    execution_path: str = "/v1/executions"
    authorization_token: str | None = None
    timeout_ms: int = Field(default=5000, ge=100, le=60000)
    function_artifacts: list[ExternalFunctionArtifact] = Field(default_factory=list)

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
    seed_user_teacher_id: str | None = None
    runner_poll_interval_seconds: float = 1.0
    runner_batch_size: int = 100
    external_executors: list[ExternalExecutorSettings] = Field(default_factory=list)
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:4173",
            "http://localhost:4173",
            "http://127.0.0.1:3000",
            "http://localhost:3000",
        ]
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
