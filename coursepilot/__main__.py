"""CoursePilot command-line configuration check."""

import argparse
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from coursepilot.config import load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coursepilot")
    parser.add_argument(
        "command",
        choices=("check-config",),
        help="validate configuration",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a bootstrap command and return a process exit code."""

    arguments = build_parser().parse_args(argv)
    try:
        settings = load_settings()
    except ValidationError as error:
        fields = ", ".join(".".join(map(str, item["loc"])) for item in error.errors())
        print(f"Invalid configuration. Check these fields: {fields}", file=sys.stderr)
        return 2

    if arguments.command == "check-config":
        print(
            "Configuration valid: "
            f"model={settings.model_name}, "
            f"llm_base_url={settings.llm_base_url or 'OpenAI default'}, "
            f"data_path={settings.data_path}"
        )
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
