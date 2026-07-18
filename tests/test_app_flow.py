from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from coursepilot.app import ProductionController
from coursepilot.config import load_settings
from coursepilot.file_store import parse_front_matter
from coursepilot.models import (
    AgentKind,
    AssignmentResult,
    AssignmentUploadPurpose,
    DimensionScore,
    MainAgentResult,
    OptimizationAnalysisResult,
    OptimizationIssue,
    ReviewResult,
    RevisionMode,
    RevisionResult,
    SourceRef,
    TeamMember,
)
from coursepilot.repositories import ConversationRepository, CourseRepository, WorkspaceRepository
from coursepilot.services import (
    AssignmentArtifactService,
    CandidateDraftService,
    WorkspaceService,
)


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


def perfect_review() -> ReviewResult:
    source = SourceRef(
        material_id="rubric",
        file_name="rubric.md",
        course_id="course-1",
        page_or_section="criteria",
        excerpt="Use evidence",
    )
    return ReviewResult(
        total_score=100,
        dimension_scores=[
            DimensionScore(
                dimension="quality",
                score=100,
                max_score=100,
                deduction=0,
                location="answer",
                evidence=[source],
                reason="Meets criteria",
                revision_advice="None",
            )
        ],
        strengths=["Clear"],
        critical_issues=[],
        likely_teacher_questions=[],
        revision_priorities=[],
    )


def test_initialized_workspace_without_course_guides_user_instead_of_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _ = configured_app(tmp_path, monkeypatch)

    app.run()

    assert not app.exception
    info_messages = [item.value for item in app.info]
    assert any("添加课程" in item for item in info_messages), info_messages
    labels = [button.label for button in app.button]
    assert "选择：上传已有作业稿" in labels
    assert "选择：上传题目资料并生成初版" in labels
    assert "选择：先整理课程资料" in labels
    next(button for button in app.button if button.label == "选择：上传已有作业稿").click().run()
    assert not app.exception
    assert any(item.label.startswith("上传你的作业稿") for item in app.get("file_uploader"))


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
    next(
        button for button in app.sidebar.button if button.label == "创建并设为当前课程"
    ).click().run()

    assert not app.exception
    index = (data_path / "courses" / "course-index.yaml").read_text(encoding="utf-8")
    assert "active_course_id: software-engineering" in index
    next(item for item in app.segmented_control if item.label == "工作区").set_value(
        "课程资料"
    ).run()
    assert any(item.label.startswith("上传课程资料") for item in app.get("file_uploader"))

    ProductionController().upload_material("第一周笔记.txt", "课程正文".encode())

    materials = list((data_path / "courses" / "software-engineering" / "materials").glob("*.md"))
    assert len(materials) == 1
    metadata, body = parse_front_matter(materials[0].read_text(encoding="utf-8"))
    assert metadata["original_file_name"] == "第一周笔记.txt"
    assert body.strip() == "课程正文"

    next(item for item in app.sidebar.text_input if item.label == "作业 ID").set_value(
        "assignment-2"
    )
    next(item for item in app.sidebar.text_input if item.label == "作业标题").set_value("第二道题")
    next(item for item in app.sidebar.text_area if item.label == "题目要求").set_value(
        "完成第二份报告"
    )
    next(
        button for button in app.sidebar.button if button.label == "创建并进入这项作业"
    ).click().run()

    assert not app.exception
    assignment_index = (data_path / "assignments" / "assignment-index.yaml").read_text(
        encoding="utf-8"
    )
    assert "active_assignment_id: assignment-2" in assignment_index
    assert (data_path / "assignments" / "assignment-2" / "assignment.md").is_file()
    assignment_selector = next(item for item in app.sidebar.selectbox if item.label == "当前作业")
    assert assignment_selector.value.id == "assignment-2"


def test_generated_candidate_runs_independent_review_without_conversation_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_path = tmp_path / "data"
    monkeypatch.setenv("COURSEPILOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("COURSEPILOT_DATA_PATH", str(data_path))
    load_settings.cache_clear()
    controller = ProductionController()
    controller.initialize_workspace("Group", "Alice", "Report", "Use evidence")
    controller.create_course("course-1", "Course", date.today(), "T", "Topic")
    workspace = WorkspaceService(WorkspaceRepository(data_path))
    course = CourseRepository(data_path).get_active()
    assert course is not None
    conversation = ConversationRepository(data_path).active("assignment-1")
    context = workspace.context(course, conversation)
    generated = MainAgentResult(
        intent=AgentKind.ASSIGNMENT,
        invoked_agents=[AgentKind.ASSIGNMENT],
        final_response="Generated",
        context=context,
        assignment_output=AssignmentResult(
            task_understanding="Write report",
            shared_answer="Candidate answer",
            course_evidence=[],
            uncertainties=[],
        ),
    )
    source = SourceRef(
        material_id="rubric",
        file_name="rubric.md",
        course_id="course-1",
        page_or_section="criteria",
        excerpt="Use evidence",
    )
    reviewed = MainAgentResult(
        intent=AgentKind.REVIEW,
        invoked_agents=[AgentKind.REVIEW],
        final_response="Reviewed",
        context=context.model_copy(update={"conversation_id": "independent-review"}),
        review_output=ReviewResult(
            total_score=100,
            dimension_scores=[
                DimensionScore(
                    dimension="quality",
                    score=100,
                    max_score=100,
                    deduction=0,
                    location="answer",
                    evidence=[source],
                    reason="Meets criteria",
                    revision_advice="None",
                )
            ],
            strengths=["Clear"],
            critical_issues=[],
            likely_teacher_questions=[],
            revision_priorities=[],
        ),
    )
    calls: list[dict[str, object]] = []

    def run_sync(*args: object, **kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            final_output=generated if len(calls) == 1 else reviewed.review_output
        )

    monkeypatch.setattr("coursepilot.app.Runner.run_sync", run_sync)
    response = controller.run_agent("完成作业")

    assert "自动审查已完成" in response
    assert "session" in calls[0]
    assert "session" not in calls[1]
    candidate = WorkspaceRepository(data_path).list_candidates()[0]
    assert candidate.status.value == "ready_for_adoption"
    assert candidate.automatic_review_id is not None
    automatic = WorkspaceRepository(data_path).get_candidate_review(candidate.automatic_review_id)
    assert automatic.review_type.value == "automatic"
    assert automatic.triggered_by == "system"


def test_production_optimization_analyzes_then_corrects_and_reviews_only_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_path = tmp_path / "data"
    monkeypatch.setenv("COURSEPILOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("COURSEPILOT_DATA_PATH", str(data_path))
    load_settings.cache_clear()
    controller = ProductionController()
    controller.initialize_workspace("Group", "Alice", "Report", "Use evidence")
    controller.create_course("course-1", "Course", date.today(), "T", "Topic")
    workspace = WorkspaceService(WorkspaceRepository(data_path))
    answer = (
        AssignmentArtifactService(data_path, workspace)
        .import_assignment(
            "answer.txt",
            b"Keep thesis. Weak evidence.",
            AssignmentUploadPurpose.INITIAL_VERSION,
            "member-1",
            "Initial",
        )
        .answer_version
    )
    assert answer is not None
    controller.create_conversation("Optimize v1", answer_version_id=answer.id)
    task = controller.start_optimization(
        mode=RevisionMode.CONSERVATIVE,
        base_answer_version_id=answer.id,
        preserve_constraints=["Keep thesis"],
    )
    source = SourceRef(
        material_id="rubric",
        file_name="rubric.md",
        course_id="course-1",
        page_or_section="criteria",
        excerpt="Use evidence",
    )
    revision_calls = 0
    review_calls = 0

    def run_sync(agent: object, *args: object, **kwargs: object) -> SimpleNamespace:
        nonlocal revision_calls, review_calls
        name = agent.name  # type: ignore[attr-defined]
        assert "session" not in kwargs
        if name == "OptimizationProblemAnalyzer":
            return SimpleNamespace(
                final_output=OptimizationAnalysisResult(
                    issues=[
                        OptimizationIssue(
                            id="citation",
                            problem="Citation missing",
                            reason="No source",
                            impact="Weak support",
                            priority=1,
                        )
                    ]
                )
            )
        if name == "DirectedRevisionAgent":
            revision_calls += 1
            return SimpleNamespace(
                final_output=RevisionResult(
                    mode=RevisionMode.CONSERVATIVE,
                    source_version=1,
                    result_version=2,
                    revised_answer=(
                        "Keep thesis. Evidence [Course p.1]."
                        if revision_calls == 2
                        else "Keep thesis. Better evidence."
                    ),
                    changes=["Improved evidence"],
                    unresolved_issues=[],
                )
            )
        if name == "IndependentReviewAgent":
            review_calls += 1
            score = 80 if review_calls == 1 else 100
            issues = ["Citation missing"] if review_calls == 1 else []
            return SimpleNamespace(
                final_output=ReviewResult(
                    total_score=score,
                    dimension_scores=[
                        DimensionScore(
                            dimension="quality",
                            score=score,
                            max_score=100,
                            deduction=100 - score,
                            location="answer",
                            evidence=[source],
                            reason="Needs citation" if issues else "Meets criteria",
                            revision_advice="Add citation" if issues else "None",
                        )
                    ],
                    strengths=["Clear"],
                    critical_issues=issues,
                    likely_teacher_questions=[],
                    revision_priorities=issues,
                )
            )
        raise AssertionError(name)

    monkeypatch.setattr("coursepilot.app.Runner.run_sync", run_sync)
    analyzed = controller.analyze_optimization(task.id)
    controller.confirm_optimization_suggestions(analyzed.id, ["citation"])
    finished = controller.generate_optimization(task.id)

    assert finished.correction_count == 1
    assert finished.fixed_issues == ["Citation missing"]
    assert finished.pending_issues == []
    assert revision_calls == 2
    assert review_calls == 2
    candidates = WorkspaceRepository(data_path).list_candidates()
    assert sorted(item.status.value for item in candidates) == [
        "ready_for_adoption",
        "superseded",
    ]


def test_guided_workspace_exposes_context_and_candidate_decisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_path = tmp_path / "data"
    monkeypatch.setenv("COURSEPILOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("COURSEPILOT_DATA_PATH", str(data_path))
    load_settings.cache_clear()
    controller = ProductionController()
    controller.initialize_workspace("Group", "Alice", "Report", "Use evidence")
    controller.create_course("course-1", "Course", date.today(), "T", "Topic")
    workspace = WorkspaceService(WorkspaceRepository(data_path))
    answer = (
        AssignmentArtifactService(data_path, workspace)
        .import_assignment(
            "answer.txt",
            b"Formal answer",
            AssignmentUploadPurpose.INITIAL_VERSION,
            "member-1",
            "Initial",
        )
        .answer_version
    )
    assert answer is not None
    conversation = controller.create_conversation("My plan", answer_version_id=answer.id)
    candidate = CandidateDraftService(data_path, workspace).create(
        "Candidate answer", conversation.id, base_answer_version_id=answer.id
    )
    CandidateDraftService(data_path, workspace).complete_automatic_review(
        candidate.id, perfect_review()
    )

    app = AppTest.from_file("coursepilot/app.py", default_timeout=10).run()
    assert not app.exception
    metric_values = {item.label: item.value for item in app.metric}
    assert metric_values["当前作业"] == "Report"
    assert metric_values["正式版本"] == "v1"
    assert metric_values["当前对话"] == "My plan"

    navigation = next(item for item in app.segmented_control if item.label == "工作区")
    navigation.set_value("作业版本").run()
    assert any(item.label.startswith("上传你的作业稿") for item in app.get("file_uploader"))
    labels = [button.label for button in app.button]
    assert "确认创建 v2 正式版本" in labels
    assert "创建定向优化任务" in labels
    assert "放弃这个候选稿" in labels
    assert "发起 v1 正式评审" in labels
    assert any("已修复 0 项" in item.value for item in app.caption)

    navigation = next(item for item in app.segmented_control if item.label == "工作区")
    navigation.set_value("对话").run()
    assert app.chat_input[0].placeholder == "说明你要生成、评审或修改什么"
    assert any(button.label == "开启新对话" for button in app.sidebar.button)

    navigation = next(item for item in app.segmented_control if item.label == "工作区")
    navigation.set_value("定向优化").run()
    assert any(item.label == "优化方向（可留空）" for item in app.text_area)
    assert any(button.label == "创建优化任务并进入下一步" for button in app.button)


def test_production_conversations_keep_prompts_sessions_and_versions_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_path = tmp_path / "data"
    monkeypatch.setenv("COURSEPILOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("COURSEPILOT_DATA_PATH", str(data_path))
    load_settings.cache_clear()
    controller = ProductionController()
    controller.initialize_workspace("Group", "Alice", "Report", "Use evidence")
    controller.create_course("course-1", "Course", date.today(), "T", "Topic")
    workspace = WorkspaceService(WorkspaceRepository(data_path))
    artifacts = AssignmentArtifactService(data_path, workspace)
    first = artifacts.import_assignment(
        "v1.txt",
        b"Formal v1",
        AssignmentUploadPurpose.INITIAL_VERSION,
        "member-1",
        "Initial",
    ).answer_version
    assert first is not None
    first_conversation = controller.create_conversation("Agent plan", answer_version_id=first.id)
    second = artifacts.import_assignment(
        "v2.txt",
        b"Formal v2",
        AssignmentUploadPurpose.NEW_FORMAL_VERSION,
        "member-1",
        "My plan",
    ).answer_version
    assert second is not None
    second_conversation = controller.create_conversation("My plan", answer_version_id=second.id)
    course = CourseRepository(data_path).get_active()
    assert course is not None
    contexts = {
        first_conversation.id: workspace.context(course, first_conversation),
        second_conversation.id: workspace.context(course, second_conversation),
    }
    calls: list[tuple[str, str]] = []
    active_context_id = [first_conversation.id]

    def run_sync(agent: object, message: str, **kwargs: object) -> SimpleNamespace:
        if getattr(agent, "name", "") == "IndependentReviewAgent":
            return SimpleNamespace(final_output=perfect_review())
        session = kwargs["session"]
        calls.append((message, session.session_id))  # type: ignore[attr-defined]
        context = contexts[active_context_id[0]]
        return SimpleNamespace(
            final_output=MainAgentResult(
                intent=AgentKind.ASSIGNMENT,
                invoked_agents=[AgentKind.ASSIGNMENT],
                final_response=f"Draft for {context.conversation_id}",
                context=context,
                assignment_output=AssignmentResult(
                    task_understanding="Produce a separate answer",
                    shared_answer=f"Answer for {context.base_answer_version_id}",
                    course_evidence=[],
                    uncertainties=[],
                ),
            )
        )

    monkeypatch.setattr("coursepilot.app.Runner.run_sync", run_sync)
    controller.activate_conversation(first_conversation.id)
    controller.run_agent("Summarize v1")
    controller.activate_conversation(second_conversation.id)
    active_context_id[0] = second_conversation.id
    controller.run_agent("Summarize v2")

    assert first.id in calls[0][0]
    assert second.id in calls[1][0]
    assert calls[0][1] != calls[1][1]
    candidates = WorkspaceRepository(data_path).list_candidates()
    by_conversation = {item.conversation_id: item for item in candidates}
    assert by_conversation[first_conversation.id].base_answer_version_id == first.id
    assert by_conversation[second_conversation.id].base_answer_version_id == second.id
    assert by_conversation[first_conversation.id].content == f"Answer for {first.id}"
    assert by_conversation[second_conversation.id].content == f"Answer for {second.id}"


def test_uploading_formal_answer_opens_version_bound_followup_conversation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_path = tmp_path / "data"
    monkeypatch.setenv("COURSEPILOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("COURSEPILOT_DATA_PATH", str(data_path))
    load_settings.cache_clear()
    controller = ProductionController()
    controller.initialize_workspace("Group", "Alice", "Report", "Use evidence")

    imported = controller.upload_assignment(
        "my-answer.txt",
        b"My revised answer",
        AssignmentUploadPurpose.INITIAL_VERSION,
        "Uploaded by the user",
    )

    assert imported.answer_version is not None
    active = ConversationRepository(data_path).active("assignment-1")
    assert active.base_answer_version_id == imported.answer_version.id
    assert active.title == "v1 后续处理"
