from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def test_streamlit_startup_disables_first_run_email_prompt() -> None:
    script = (PROJECT_ROOT / "start.ps1").read_text(encoding="utf-8")
    config = (PROJECT_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")

    assert "--browser.gatherUsageStats=false" in script
    assert "gatherUsageStats = false" in config
