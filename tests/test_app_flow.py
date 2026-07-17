from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from coursepilot.app import ProductionController
from coursepilot.config import load_settings
from coursepilot.file_store import parse_front_matter
from coursepilot.models import TeamMember
from coursepilot.repositories import WorkspaceRepository


def configured_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, initialized: bool = True
) -> tuple[AppTest, Path]:
    data_path = tmp_path / "data"
    monkeypatch.setenv("COURSEPILOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("COURSEPILOT_DATA_PATH", str(data_path))
    load_settings.cache_clear()
    if initialized:
        workspace = WorkspaceRepository(data_path)
        workspace.initialize_team("测试小组", [TeamMember(id="member-1", name="测试成员")])
        workspace.initialize_assignment("唯一大作业", "完成课程报告", None)
    app = AppTest.from_file("coursepilot/app.py", default_timeout=10)
    return app, data_path


def test_initialized_workspace_without_course_guides_user_instead_of_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _ = configured_app(tmp_path, monkeypatch)

    app.run()

    assert not app.exception
    info_messages = [item.value for item in app.info]
    assert any("创建课程" in item for item in info_messages), info_messages
    assert app.get("file_uploader")[0].disabled is True


def test_first_use_flow_initializes_workspace_and_activates_first_course(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, data_path = configured_app(tmp_path, monkeypatch, initialized=False)
    app.run()

    app.text_input[0].set_value("测试小组")
    app.text_input[1].set_value("测试成员")
    app.text_input[2].set_value("唯一大作业")
    app.text_area[0].set_value("完成课程报告")
    app.button[0].click().run()

    assert not app.exception
    assert (data_path / "workspace.yaml").is_file()
    assert (data_path / "assignments" / "assignment-1" / "assignment.md").is_file()

    app = AppTest.from_file("coursepilot/app.py", default_timeout=10)
    app.run()
    sidebar_inputs = app.sidebar.text_input
    sidebar_inputs[0].set_value("软件工程")
    sidebar_inputs[1].set_value("software-engineering")
    sidebar_inputs[2].set_value("张老师")
    sidebar_inputs[3].set_value("需求与架构")
    next(button for button in app.sidebar.button if button.label == "创建课程").click().run()

    assert not app.exception
    index = (data_path / "courses" / "course-index.yaml").read_text(encoding="utf-8")
    assert "active_course_id: software-engineering" in index
    assert app.get("file_uploader")[0].disabled is False

    ProductionController().upload_material("第一周笔记.txt", "课程正文".encode())

    materials = list((data_path / "courses" / "software-engineering" / "materials").glob("*.md"))
    assert len(materials) == 1
    metadata, body = parse_front_matter(materials[0].read_text(encoding="utf-8"))
    assert metadata["original_file_name"] == "第一周笔记.txt"
    assert body.strip() == "课程正文"

    next(item for item in app.sidebar.text_input if item.label == "题目 ID").set_value(
        "assignment-2"
    )
    next(item for item in app.sidebar.text_input if item.label == "题目标题").set_value("第二道题")
    next(item for item in app.sidebar.text_area if item.label == "题目要求").set_value(
        "完成第二份报告"
    )
    next(button for button in app.sidebar.button if button.label == "创建题目").click().run()

    assert not app.exception
    assignment_index = (data_path / "assignments" / "assignment-index.yaml").read_text(
        encoding="utf-8"
    )
    assert "active_assignment_id: assignment-2" in assignment_index
    assert (data_path / "assignments" / "assignment-2" / "assignment.md").is_file()
    assignment_selector = next(item for item in app.sidebar.selectbox if item.label == "切换题目")
    assert assignment_selector.value.id == "assignment-2"
