from pathlib import Path

import pytest
from pydantic import ValidationError

from coursepilot.config.settings import Settings, load_settings


def test_load_settings_reads_llm_and_local_library_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COURSEPILOT_LLM_API_KEY", "test-secret")
    monkeypatch.setenv("COURSEPILOT_DATA_PATH", "var/data")
    monkeypatch.setenv("COURSEPILOT_FULL_CONTEXT_CHARS", "40000")
    load_settings.cache_clear()

    settings = load_settings()

    assert settings.llm_api_key.get_secret_value() == "test-secret"
    assert settings.data_path == Path("var/data")
    assert settings.full_context_chars == 40_000
    assert "test-secret" not in repr(settings)


def test_only_llm_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COURSEPILOT_LLM_API_KEY", raising=False)

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)

    missing = {item["loc"] for item in error.value.errors() if item["type"] == "missing"}
    assert missing == {("llm_api_key",)}


def test_settings_rejects_unsafe_limits() -> None:
    with pytest.raises(ValidationError):
        Settings(
            llm_api_key="test-key",
            max_upload_mb=0,
            max_search_results=0,
            full_context_chars=0,
            request_timeout_seconds=0,
            max_retries=-1,
            _env_file=None,
        )


def test_openai_compatible_provider_configuration() -> None:
    settings = Settings(
        llm_api_key="third-party-key",
        llm_base_url="https://llm.example.com/v1",
        model_name="provider-model",
        _env_file=None,
    )

    assert settings.llm_api_key.get_secret_value() == "third-party-key"
    assert settings.llm_base_url == "https://llm.example.com/v1"
    assert settings.model_name == "provider-model"
