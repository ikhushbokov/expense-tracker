"""Centralized, typed configuration loaded from environment variables / .env.

Every tunable value (Telegram token, LLM endpoint, database path, OCR
settings, ...) lives here so the rest of the codebase never hardcodes
secrets or paths. Import the module-level ``settings`` instance anywhere
configuration is needed.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings, populated from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram -----------------------------------------------------
    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_user_id: int | None = Field(default=None, alias="TELEGRAM_ALLOWED_USER_ID")

    # --- LLM ------------------------------------------------------------
    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_timeout_seconds: float = Field(default=30.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=2, alias="LLM_MAX_RETRIES")
    # Only meaningful for reasoning models (e.g. o-series, gpt-5.x). Left empty
    # to omit the parameter entirely for providers/models that don't support it.
    llm_reasoning_effort: str = Field(default="", alias="LLM_REASONING_EFFORT")
    # How often (seconds) to retry messages queued while the LLM was down.
    retry_queue_interval_seconds: float = Field(default=60.0, alias="RETRY_QUEUE_INTERVAL_SECONDS")

    # --- Database ---------------------------------------------------------
    database_path: str = Field(default="data/expenses.db", alias="DATABASE_PATH")

    # --- Currency -----------------------------------------------------
    default_currency: str = Field(default="UZS", alias="DEFAULT_CURRENCY")

    # --- Timezone ---------------------------------------------------------
    # IANA name (e.g. "Asia/Tashkent"). Every "today"/"this week" boundary,
    # history-log date, and stored timestamp is computed in this timezone.
    # Defaults to UTC -- important to set explicitly for Docker, since a
    # container's system clock is UTC by default regardless of the host
    # machine's timezone (see bot.py's use of this at startup).
    timezone: str = Field(default="UTC", alias="TZ")

    # --- OCR ------------------------------------------------------------
    tesseract_cmd: str = Field(default="tesseract", alias="TESSERACT_CMD")
    ocr_languages: str = Field(default="eng", alias="OCR_LANGUAGES")

    # --- Logging --------------------------------------------------------
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(default="logs/bot.log", alias="LOG_FILE")

    # --- Exports --------------------------------------------------------
    export_dir: str = Field(default="exports", alias="EXPORT_DIR")

    @field_validator("telegram_allowed_user_id", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: object) -> object:
        if v == "" or v is None:
            return None
        return v

    @property
    def database_full_path(self) -> Path:
        path = Path(self.database_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def log_file_full_path(self) -> Path:
        path = Path(self.log_file)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def export_dir_full_path(self) -> Path:
        path = Path(self.export_dir)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    """Return a cached, process-wide Settings instance."""
    return Settings()


settings = get_settings()
