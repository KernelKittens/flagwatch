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
    ctftime_base_url: HttpUrl = HttpUrl("https://ctftime.org/api/v1")
    ctftime_lookahead_days: int = 90
    request_timeout_seconds: float = 10.0
    max_response_bytes: int = 2 * 1024 * 1024
    send_enabled: bool = False
    discord_webhook_url: SecretStr | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_to: str | None = None
    ai_enabled: bool = False
    ai_endpoint: HttpUrl = HttpUrl(
        "https://kitsunetechnologies.services.ai.azure.com/openai/v1/chat/completions"
    )
    ai_model: str = "DeepSeek-V4-Flash"
    ai_api_key: SecretStr | None = None
