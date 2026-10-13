from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WF_", env_file=".env", extra="ignore")

    user_agent: str = "CommonTools-WeatherFishing/0.1"
    api_key: SecretStr = SecretStr("")
    ncei_token: SecretStr = SecretStr("")
    solunar_permission_reference: str = ""
    quota_database: Path = Path("data/quota.sqlite3")
    request_timeout: float = Field(default=15, ge=1, le=30)
    tool_timeout: float = Field(default=50, ge=5, le=60)
    max_response_bytes: int = Field(default=5_000_000, ge=1000, le=10_000_000)
    cache_entries: int = Field(default=48, ge=0, le=128)
    cache_bytes: int = Field(default=20_000_000, ge=0, le=100_000_000)
