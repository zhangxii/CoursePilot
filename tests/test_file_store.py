from pathlib import Path

import pytest

from coursepilot.file_store import FileDataStore, parse_front_matter, render_front_matter


def test_file_store_round_trips_yaml_and_markdown_atomically(tmp_path: Path) -> None:
    store = FileDataStore(tmp_path / "data")
    store.write_yaml("workspace.yaml", {"team": "CoursePilot", "members": ["张同学"]})
    store.write_text(
        "courses/course-1/materials/material.md",
        render_front_matter({"course_id": "course-1"}, "# Module design"),
    )

    metadata, body = parse_front_matter(store.read_text("courses/course-1/materials/material.md"))

    assert store.read_yaml("workspace.yaml")["team"] == "CoursePilot"
    assert metadata == {"course_id": "course-1"}
    assert body.strip() == "# Module design"


def test_file_store_rejects_paths_outside_data_root(tmp_path: Path) -> None:
    store = FileDataStore(tmp_path / "data")

    with pytest.raises(ValueError, match="escapes"):
        store.write_text("../outside.md", "unsafe")
