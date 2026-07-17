"""Validated runtime settings loaded from environment variables or ``.env``."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class Settings(BaseSettings):
    """CoursePilot configuration with safe defaults for non-secret values."""

    model_config = SettingsConfigDict(
        env_prefix="COURSEPILOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    llm_api_key: SecretStr
    llm_base_url: str | None = None
    model_name: Annotated[str, Field(min_length=1)] = "gpt-5-mini"
    data_path: Path = Path("data")
    max_upload_mb: PositiveInt = 50
    max_search_results: PositiveInt = 5
    full_context_chars: PositiveInt = 60_000
    request_timeout_seconds: PositiveInt = 60
    max_retries: NonNegativeInt = 2


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    """Load and cache the process-wide validated settings."""

    return Settings()
