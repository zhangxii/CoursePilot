from pathlib import Path

import pytest
from pydantic import ValidationError

from coursepilot.config.settings import Settings, load_settings


def test_load_settings_reads_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COURSEPILOT_OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("COURSEPILOT_VECTOR_STORE_ID", "vs_test")
    monkeypatch.setenv("COURSEPILOT_DATABASE_PATH", "var/test.db")
    load_settings.cache_clear()

    settings = load_settings()

    assert settings.openai_api_key.get_secret_value() == "sk-test-secret"
    assert settings.vector_store_id == "vs_test"
    assert settings.database_path == Path("var/test.db")
    assert settings.max_search_results == 5
    assert "sk-test-secret" not in repr(settings)


def test_missing_required_settings_reports_all_missing_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COURSEPILOT_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("COURSEPILOT_VECTOR_STORE_ID", raising=False)

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)

    missing = {item["loc"] for item in error.value.errors() if item["type"] == "missing"}
    assert missing == {("openai_api_key",), ("vector_store_id",)}


def test_settings_rejects_unsafe_limits() -> None:
    with pytest.raises(ValidationError):
        Settings(
            openai_api_key="sk-test",
            vector_store_id="vs_test",
            max_upload_mb=0,
            max_search_results=0,
            request_timeout_seconds=0,
            max_retries=-1,
            _env_file=None,
        )
