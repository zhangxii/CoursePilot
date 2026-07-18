from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from coursepilot.agent_runtime import FileAgentRuntime
from coursepilot.file_store import FileDataStore
from coursepilot.models import (
    AssignmentUploadPurpose,
    DimensionScore,
    OptimizationDirectionSource,
    OptimizationIssue,
    OptimizationTaskStatus,
    ReviewResult,
    RevisionMode,
    SourceRef,
    TeamMember,
)
from coursepilot.repositories import ConversationRepository, WorkspaceRepository
from coursepilot.services import (
    AssignmentArtifactService,
    ConversationService,
    OptimizationService,
    WorkspaceService,
)


def review(*issues: str) -> ReviewResult:
    score = 100 if not issues else 80
    return ReviewResult(
        total_score=score,
        dimension_scores=[
            DimensionScore(
                dimension="quality",
                score=score,
                max_score=100,
                deduction=100 - score,
                location="answer",
                evidence=[
                    SourceRef(
                        material_id="rubric",
                        file_name="rubric.md",
                        course_id="course-1",
                        page_or_section="criteria",
                        excerpt="Use cited evidence",
                    )
                ],
                reason="Pass" if not issues else issues[0],
                revision_advice="None" if not issues else "Add citation",
            )
        ],
        strengths=["clear"],
        critical_issues=list(issues),
        likely_teacher_questions=[],
        revision_priorities=list(issues),
    )


def setup(tmp_path: Path) -> tuple[WorkspaceService, str, str]:
    data_root = tmp_path / "data"
    workspace = WorkspaceService(WorkspaceRepository(data_root))
    workspace.initialize_team("Group", [TeamMember(id="alice", name="Alice")])
    workspace.initialize_assignment("Report", "Write it")
    answer = (
        AssignmentArtifactService(data_root, workspace)
        .import_assignment(
            "v1.txt",
            b"Keep thesis. Weak evidence.",
            AssignmentUploadPurpose.INITIAL_VERSION,
            "alice",
            "Initial",
        )
        .answer_version
    )
    assert answer is not None
    conversation = ConversationService(
        ConversationRepository(data_root), workspace, FileAgentRuntime(data_root)
    ).create("Optimize")
    return workspace, answer.id, conversation.id


def docx_bytes(text: str) -> bytes:
    target = BytesIO()
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
                f"{text}</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
    return target.getvalue()


def test_direction_text_and_file_create_previewable_isolated_tasks(tmp_path: Path) -> None:
    workspace, answer_id, conversation_id = setup(tmp_path)
    service = OptimizationService(tmp_path / "data", workspace)
    typed = service.create_for_answer(
        conversation_id,
        answer_id,
        RevisionMode.CONSERVATIVE,
        user_direction="Strengthen evidence",
        preserve_constraints=["Keep thesis"],
    )
    uploaded = service.create_for_answer(conversation_id, answer_id, RevisionMode.DEEP_RESTRUCTURE)
    uploaded = service.attach_direction(uploaded.id, "direction.md", b"Reorder sections")
    docx_task = service.create_for_answer(conversation_id, answer_id, RevisionMode.DEEP_RESTRUCTURE)
    docx_task = service.attach_direction(
        docx_task.id, "direction.docx", docx_bytes("Use a comparison table")
    )

    assert typed.direction_text == "Strengthen evidence"
    assert typed.direction_source is OptimizationDirectionSource.USER_TEXT
    assert uploaded.direction_text == "Reorder sections"
    assert uploaded.direction_attachment_id is not None
    assert uploaded.direction_source is OptimizationDirectionSource.USER_UPLOAD
    assert docx_task.direction_text == "Use a comparison table"
    assert workspace.list_answers()[0].content == "Keep thesis. Weak evidence."
    assignment_attachments = WorkspaceRepository(tmp_path / "data").list_attachments()
    assert len(assignment_attachments) == 1
    assert all(item.purpose.value != "optimization_direction" for item in assignment_attachments)


def test_no_direction_requires_confirmed_problem_analysis_before_generation(tmp_path: Path) -> None:
    workspace, answer_id, conversation_id = setup(tmp_path)
    service = OptimizationService(tmp_path / "data", workspace)
    task = service.create_for_answer(conversation_id, answer_id, RevisionMode.CONSERVATIVE)

    class Analyzer:
        request: object | None = None

        def analyze(self, request: object) -> list[OptimizationIssue]:
            self.request = request
            return [
                OptimizationIssue(
                    id="evidence",
                    problem="Evidence is weak",
                    reason="No course citation",
                    impact="Lower credibility",
                    priority=1,
                )
            ]

    analyzer = Analyzer()
    issues = service.analyze_problems(task.id, analyzer)
    assert issues.status is OptimizationTaskStatus.AWAITING_SELECTION
    assert analyzer.request is not None
    assert "conversation" not in analyzer.request.model_dump()  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="confirmed direction"):
        service.create_candidate(task.id, "Premature")

    confirmed = service.confirm_suggestions(
        task.id, ["evidence"], supplemental_direction="Keep the example"
    )
    assert confirmed.direction_source is OptimizationDirectionSource.AGENT_ANALYSIS
    assert "Keep the example" in (confirmed.direction_text or "")
    candidate = service.create_candidate(confirmed.id, "Keep thesis. Strong evidence.")
    assert candidate.status.value == "draft"
    assert service.get(task.id).status is OptimizationTaskStatus.CANDIDATE_DRAFTED


def test_independent_review_allows_only_one_correction_and_re_review(tmp_path: Path) -> None:
    workspace, answer_id, conversation_id = setup(tmp_path)
    service = OptimizationService(tmp_path / "data", workspace)
    task = service.create_for_answer(
        conversation_id,
        answer_id,
        RevisionMode.CONSERVATIVE,
        user_direction="Strengthen evidence",
        preserve_constraints=["Keep thesis"],
        prohibited_changes=["Remove thesis"],
        format_constraints=["Under 100 words"],
    )
    first = service.create_candidate(task.id, "Keep thesis. Better evidence.")
    reviewed = service.record_automatic_review(
        task.id,
        first.id,
        review("Citation missing"),
        auto_fixable_issues=["Citation missing"],
    )
    assert service.candidates.get(first.id).status.value == "draft"
    with pytest.raises(ValueError, match="newly drafted"):
        service.record_automatic_review(task.id, first.id, review())
    corrected = service.apply_bounded_correction(
        reviewed.id,
        "Keep thesis. Better evidence [Course p.1].",
        review(),
        fixed_issues=["Citation missing"],
    )

    assert corrected.correction_count == 1
    assert corrected.status is OptimizationTaskStatus.READY_FOR_DECISION
    assert service.candidates.get(corrected.result_candidate_id).status.value == (
        "ready_for_adoption"
    )
    with pytest.raises(ValueError, match="at most one correction"):
        service.apply_bounded_correction(corrected.id, "Again", review())


def test_automatic_review_contract_excludes_conversation_and_correction_is_bounded(
    tmp_path: Path,
) -> None:
    workspace, answer_id, conversation_id = setup(tmp_path)
    service = OptimizationService(tmp_path / "data", workspace)
    task = service.create_for_answer(
        conversation_id,
        answer_id,
        RevisionMode.CONSERVATIVE,
        user_direction="Strengthen evidence",
        preserve_constraints=["Keep thesis"],
    )
    candidate = service.create_candidate(task.id, "Keep thesis. Better evidence.")

    class Reviewer:
        def __init__(self) -> None:
            self.requests: list[object] = []

        def review(self, request: object) -> ReviewResult:
            self.requests.append(request)
            return review("Citation missing") if len(self.requests) == 1 else review()

    class Corrector:
        calls = 0

        def correct(self, request: object) -> str:
            self.calls += 1
            return "Keep thesis. Better evidence [Course p.1]."

    reviewer = Reviewer()
    corrector = Corrector()
    finished = service.run_automatic_review(task.id, reviewer, corrector=corrector)

    assert finished.status is OptimizationTaskStatus.READY_FOR_DECISION
    assert finished.correction_count == 1
    assert corrector.calls == 1
    assert len(reviewer.requests) == 2
    assert all("conversation" not in request.model_dump() for request in reviewer.requests)  # type: ignore[union-attr]
    assert service.candidates.get(candidate.id).status.value == "superseded"


def test_candidate_base_and_restructure_constraints_remain_enforced(tmp_path: Path) -> None:
    workspace, answer_id, conversation_id = setup(tmp_path)
    service = OptimizationService(tmp_path / "data", workspace)
    source = service.candidates.create(
        "Candidate base", conversation_id, base_answer_version_id=answer_id
    )
    task = service.create_for_candidate(
        conversation_id,
        source.id,
        RevisionMode.DEEP_RESTRUCTURE,
        user_direction="Rework",
        prohibited_changes=["Forbidden phrase"],
        max_words=3,
    )
    with pytest.raises(ValueError, match="prohibited"):
        service.create_candidate(task.id, "Forbidden phrase")
    with pytest.raises(ValueError, match="word limit"):
        service.create_candidate(task.id, "one two three four")

    result = service.create_candidate(task.id, "Better draft")
    assert result.derived_from_candidate_id == source.id
    assert result.base_answer_version_id == answer_id

    chinese = service.create_for_answer(
        conversation_id,
        answer_id,
        RevisionMode.DEEP_RESTRUCTURE,
        user_direction="精简",
        max_characters=4,
    )
    with pytest.raises(ValueError, match="character limit"):
        service.create_candidate(chinese.id, "一二三四五")


def test_optimization_task_cannot_be_read_or_changed_from_another_assignment(
    tmp_path: Path,
) -> None:
    workspace, answer_id, conversation_id = setup(tmp_path)
    service = OptimizationService(tmp_path / "data", workspace)
    task = service.create_for_answer(
        conversation_id,
        answer_id,
        RevisionMode.CONSERVATIVE,
        user_direction="Improve",
    )
    workspace.create_assignment("assignment-2", "Other", "Other task")

    with pytest.raises(KeyError):
        service.get(task.id)
    with pytest.raises(KeyError):
        service.attach_direction(task.id, "direction.txt", b"Cross assignment")


def test_candidate_optimization_rejects_a_different_conversation(tmp_path: Path) -> None:
    workspace, answer_id, conversation_id = setup(tmp_path)
    service = OptimizationService(tmp_path / "data", workspace)
    candidate = service.candidates.create(
        "Candidate", conversation_id, base_answer_version_id=answer_id
    )
    other = ConversationService(
        ConversationRepository(tmp_path / "data"),
        workspace,
        FileAgentRuntime(tmp_path / "data"),
    ).create("Other")

    with pytest.raises(ValueError, match="selected conversation"):
        service.create_for_candidate(
            other.id,
            candidate.id,
            RevisionMode.CONSERVATIVE,
            user_direction="Improve",
        )


def test_answer_optimization_must_use_the_conversation_bound_version(tmp_path: Path) -> None:
    workspace, _, conversation_id = setup(tmp_path)
    newer = (
        AssignmentArtifactService(tmp_path / "data", workspace)
        .import_assignment(
            "v2.txt",
            b"New formal version",
            AssignmentUploadPurpose.NEW_FORMAL_VERSION,
            "alice",
            "New",
        )
        .answer_version
    )
    assert newer is not None
    service = OptimizationService(tmp_path / "data", workspace)

    with pytest.raises(ValueError, match="selected conversation"):
        service.create_for_answer(
            conversation_id,
            newer.id,
            RevisionMode.CONSERVATIVE,
            user_direction="Improve",
        )


def test_correction_transaction_rolls_back_candidate_review_and_task_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, answer_id, conversation_id = setup(tmp_path)
    service = OptimizationService(tmp_path / "data", workspace)
    task = service.create_for_answer(
        conversation_id,
        answer_id,
        RevisionMode.CONSERVATIVE,
        user_direction="Improve evidence",
        preserve_constraints=["Keep thesis"],
    )
    candidate = service.create_candidate(task.id, "Keep thesis. Evidence.")
    reviewed = service.record_automatic_review(
        task.id,
        candidate.id,
        review("Citation missing"),
        auto_fixable_issues=["Citation missing"],
    )
    original_apply = FileDataStore._apply_batch

    def fail_after_writes(store: FileDataStore, payload: object) -> None:
        original_apply(store, payload)
        raise OSError("simulated correction failure")

    monkeypatch.setattr(FileDataStore, "_apply_batch", fail_after_writes)
    with pytest.raises(OSError, match="simulated correction failure"):
        service.apply_bounded_correction(
            reviewed.id,
            "Keep thesis. Evidence [Course p.1].",
            review(),
            fixed_issues=["Citation missing"],
        )

    restored = OptimizationService(tmp_path / "data", workspace)
    assert restored.get(task.id).status is OptimizationTaskStatus.REVIEWED
    assert restored.candidates.get(candidate.id).status.value == "draft"
    assert [item.id for item in WorkspaceRepository(tmp_path / "data").list_candidates()] == [
        candidate.id
    ]
