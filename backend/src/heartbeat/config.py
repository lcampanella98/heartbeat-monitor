from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the repo-root .env deterministically regardless of CWD.
_REPO_ROOT = Path(__file__).parent.parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str  # required — no default; startup fails immediately if unset
    check_source: Literal["real", "simulated"] = "real"
    email_sink: Literal["smtp", "log"] = "smtp"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-oss-120b"
    scheduler_concurrency: int = 50
    log_level: str = "INFO"


settings = Settings()
