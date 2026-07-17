from pathlib import Path

import pytest

from coursepilot.__main__ import main
from coursepilot.config import load_settings


def configure(monkeypatch: pytest.MonkeyPatch, data_path: Path) -> None:
    monkeypatch.setenv("COURSEPILOT_LLM_API_KEY", "never-print-this")
    monkeypatch.setenv("COURSEPILOT_DATA_PATH", str(data_path))
    load_settings.cache_clear()


def test_check_config_reports_safe_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(monkeypatch, tmp_path / "data")

    exit_code = main(["check-config"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Configuration valid" in output
    assert "never-print-this" not in output
