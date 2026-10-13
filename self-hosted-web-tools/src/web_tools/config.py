from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_host: str = "127.0.0.1"
    app_port: int = Field(8000, ge=1, le=65535)
    api_key: SecretStr
    human_approval_key: SecretStr | None = None
    searxng_base_url: str = "http://127.0.0.1:8080"
    browser_headless: bool = True
    browser_max_sessions: int = Field(3, ge=1, le=20)
    browser_session_timeout_seconds: int = Field(900, ge=10)
    browser_enabled: bool = True
    download_directory: Path = Path("data/downloads")
    database_url: str = "sqlite:///data/webtools.db"
    max_download_size_mb: int = Field(100, ge=1, le=1024)
    storage_quota_mb: int = Field(1024, ge=1)
    http_request_timeout_seconds: float = Field(30, gt=0, le=120)
    tool_timeout_seconds: float = Field(60, ge=5, le=300)
    max_fetch_chars: int = Field(12000, ge=100, le=100000)
    max_tool_response_chars: int = Field(24000, ge=4000, le=100000)
    max_fetch_bytes: int = Field(2_000_000, ge=1024, le=10_000_000)
    max_search_bytes: int = Field(2_000_000, ge=1024)
    browser_max_response_bytes: int = Field(10_000_000, ge=1024, le=100_000_000)
    allowed_ports: list[int] = [80, 443]
    test_allowed_origins: list[str] = []
    environment: str = "production"
    mcp_allowed_hosts: list[str] = ["localhost:*", "127.0.0.1:*", "[::1]:*"]
    log_level: str = "INFO"

    @field_validator("human_approval_key", mode="before")
    @classmethod
    def empty_optional_key(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def secure_defaults(self):
        if len(self.api_key.get_secret_value()) < 24:
            raise ValueError("API_KEY must contain at least 24 characters")
        if self.human_approval_key:
            key = self.human_approval_key.get_secret_value()
            if len(key) < 24 or key == self.api_key.get_secret_value():
                raise ValueError("HUMAN_APPROVAL_KEY must be distinct and at least 24 characters")
        if self.test_allowed_origins and self.environment != "test":
            raise ValueError("TEST_ALLOWED_ORIGINS is permitted only with ENVIRONMENT=test")
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("Only SQLite DATABASE_URL is supported")
        return self

    @property
    def database_path(self) -> Path:
        return Path(self.database_url.removeprefix("sqlite:///"))

    @property
    def max_download_bytes(self) -> int:
        return self.max_download_size_mb * 1024 * 1024
