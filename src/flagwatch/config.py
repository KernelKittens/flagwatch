from __future__ import annotations

from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FLAGWATCH_",
        env_file=(".env", ".env.local"),
        extra="ignore",
    )

    database_path: Path = Field(default_factory=lambda: Path.cwd() / "data" / "flagwatch.db")
    ctftime_enabled: bool = False
    ctftime_base_url: HttpUrl = HttpUrl("https://ctftime.org/api/v1")
    ctftime_lookback_days: int = Field(default=31, ge=1, le=366)
    ctftime_lookahead_days: int = Field(default=90, ge=1, le=366)
    request_timeout_seconds: float = 10.0
    max_response_bytes: int = 2 * 1024 * 1024
    sources_path: Path | None = None
    sources_json: str | None = None
    send_enabled: bool = False
    discord_webhook_url: SecretStr | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_to: str | None = None
    ai_enabled: bool = False
    ai_provider: str = "openai"
    ai_endpoint: HttpUrl = HttpUrl("https://api.openai.com/v1")
    ai_model: str = "gpt-5-mini"
    ai_api_key: SecretStr | None = None
    ai_timeout_seconds: float = Field(default=60.0, ge=5.0, le=300.0)
