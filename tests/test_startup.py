import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def test_streamlit_startup_disables_first_run_email_prompt() -> None:
    script = (PROJECT_ROOT / "start.ps1").read_text(encoding="utf-8")
    config = (PROJECT_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")

    assert "--server.showEmailPrompt=false" in script
    assert "showEmailPrompt = false" in config
    assert "--browser.gatherUsageStats=false" in script
    assert "gatherUsageStats = false" in config


def test_streamlit_script_path_does_not_shadow_agents_sdk() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.path.insert(0, 'coursepilot'); "
                "from agents import Agent; "
                "print(Agent.__module__)"
            ),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip().startswith("agents.")
