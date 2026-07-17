from pathlib import Path

import pytest

from coursepilot.__main__ import main
from coursepilot.config import load_settings


def configure(monkeypatch: pytest.MonkeyPatch, database: Path) -> None:
    monkeypatch.setenv("COURSEPILOT_LLM_API_KEY", "never-print-this")
    monkeypatch.setenv("COURSEPILOT_DATABASE_PATH", str(database))
    load_settings.cache_clear()


def test_check_config_reports_safe_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(monkeypatch, tmp_path / "coursepilot.db")

    exit_code = main(["check-config"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Configuration valid" in output
    assert "never-print-this" not in output


def test_init_db_creates_configured_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "data" / "coursepilot.db"
    configure(monkeypatch, database)

    exit_code = main(["init-db"])

    assert exit_code == 0
    assert database.exists()
    assert "Database initialized" in capsys.readouterr().out
