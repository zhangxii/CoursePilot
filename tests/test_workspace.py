from datetime import date
from pathlib import Path

import pytest

from coursepilot.file_store import FileDataStore, render_front_matter
from coursepilot.models import (
    AgentKind,
    AssignmentResult,
    Course,
    DimensionScore,
    MainAgentResult,
    ReviewRecord,
    ReviewResult,
    RevisionMode,
    RevisionRecord,
    RevisionResult,
    SourceRef,
    TeamMember,
)
from coursepilot.repositories import WorkspaceRepository
from coursepilot.services import WorkspaceService


def review() -> ReviewResult:
    source = SourceRef(
        material_id="m1",
        file_name="rubric.md",
        course_id="architecture",
        page_or_section="page 2",
        excerpt="Explain tradeoffs",
    )
    return ReviewResult(
        total_score=80,
        dimension_scores=[
            DimensionScore(
                dimension="tradeoffs",
                score=80,
                max_score=100,
                deduction=20,
                location="section 2",
                evidence=[source],
                reason="Missing alternatives",
                revision_advice="Compare two alternatives",
            )
        ],
        strengths=["Clear structure"],
        critical_issues=["Missing alternatives"],
        likely_teacher_questions=["Why this design?"],
        revision_priorities=["Add comparison"],
    )


def test_single_workspace_versions_review_and_revision_survive_restart(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    service = WorkspaceService(WorkspaceRepository(data_root))
    service.initialize_team("Architecture Group", [TeamMember(id="alice", name="Alice")])
    service.initialize_assignment("CoursePilot", "Design and implement the system", "100 points")
    first = service.save_answer("Version one", "alice")
    saved_review = service.save_review(first.id, review())
    second, revision = service.revise(
        first,
        saved_review,
        "Version two with alternatives",
        "alice",
        RevisionMode.CONSERVATIVE,
        "Added alternatives",
    )

    restored = WorkspaceService(WorkspaceRepository(data_root))
    course = Course(
        id="architecture",
        name="Architecture",
        course_date=date(2026, 7, 17),
        teacher="Teacher",
        topic="Design",
        is_active=True,
    )
    context = restored.context(course)

    assert second.version == 2
    assert revision.source_answer_id == first.id
    assert context.current_answer == "Version two with alternatives"
    assert context.answer_version == 2
    assert restored.get_assignment().title == "CoursePilot"
    comparison = restored.compare_revision(revision)
    assert comparison.operated_by_member_id == "alice"
    assert comparison.resolved_issues == ["Missing alternatives"]


def test_invalid_revision_rolls_back_answer_and_revision_together(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    service = WorkspaceService(WorkspaceRepository(data_root))
    service.initialize_team("Group", [TeamMember(id="alice", name="Alice")])
    service.initialize_assignment("Only", "Do it")
    first = service.save_answer("Draft", "alice")
    saved_review = service.save_review(first.id, review())

    with pytest.raises(ValueError):
        service.revise(
            first,
            saved_review,
            "Should not persist",
            "alice",
            RevisionMode.CONSERVATIVE,
            "",
        )

    assert (
        service.context(
            Course(
                id="architecture",
                name="Architecture",
                course_date=date(2026, 7, 17),
                teacher="Teacher",
                topic="Design",
                is_active=True,
            )
        ).answer_version
        == 1
    )


def test_second_team_is_rejected_but_multiple_assignments_are_isolated(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    repository = WorkspaceRepository(data_root)
    service = WorkspaceService(repository)
    service.initialize_team("One", [TeamMember(id="alice", name="Alice")])
    first_assignment = service.initialize_assignment("First assignment", "Do it")
    first_answer = service.save_answer("First answer", "alice")
    service.save_review(first_answer.id, review())

    with pytest.raises(ValueError, match="one team"):
        service.initialize_team("Two", [TeamMember(id="bob", name="Bob")])

    second_assignment = service.create_assignment("assignment-2", "Second", "Also do it")
    second_answer = service.save_answer("Second answer", "alice")

    assert first_assignment.id != second_assignment.id
    assert first_answer.assignment_id == first_assignment.id
    assert second_answer.assignment_id == second_assignment.id
    assert first_answer.version == second_answer.version == 1
    assert repository.latest_review(second_answer.id) is None
    service.activate_assignment(first_assignment.id)
    assert service.get_assignment().id == first_assignment.id
    assert service.latest_answer().content == "First answer"
    assert service.save_answer("First answer v2", "alice").version == 2


def test_legacy_single_assignment_files_migrate_without_losing_answer(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    store = FileDataStore(data_root)
    store.write_text(
        "assignment/assignment.md",
        render_front_matter(
            {"id": "main_assignment", "title": "Legacy question", "rubric": None},
            "Legacy requirements",
        ),
    )
    store.write_text(
        "assignment/answers/0001.md",
        render_front_matter(
            {"id": "legacy-answer", "version": 1, "operated_by_member_id": "alice"},
            "Legacy answer",
        ),
    )
    store.write_text(
        "assignment/answers/0002.md",
        render_front_matter(
            {"id": "legacy-answer-2", "version": 2, "operated_by_member_id": "alice"},
            "Legacy revised answer",
        ),
    )
    legacy_review = ReviewRecord(id="legacy-review", answer_id="legacy-answer", result=review())
    store.write_yaml("assignment/reviews/legacy-review.yaml", legacy_review.model_dump(mode="json"))
    legacy_revision = RevisionRecord(
        id="legacy-revision",
        source_answer_id="legacy-answer",
        review_id=legacy_review.id,
        result_answer_id="legacy-answer-2",
        mode=RevisionMode.CONSERVATIVE,
        change_summary="Legacy changes",
    )
    store.write_yaml("assignment/revisions/0002.yaml", legacy_revision.model_dump(mode="json"))

    repository = WorkspaceRepository(data_root)

    assert repository.get_assignment().id == "assignment-1"
    assert repository.latest_answer().content == "Legacy revised answer"
    assert repository.latest_answer().assignment_id == "assignment-1"
    migrated_review = repository.latest_review("legacy-answer")
    migrated_revision = repository.latest_revision()
    assert migrated_review is not None and migrated_review.id == "legacy-review"
    assert migrated_revision is not None and migrated_revision.id == "legacy-revision"


def test_agent_outputs_are_persisted_as_shared_reviewed_revision(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    service = WorkspaceService(WorkspaceRepository(data_root))
    service.initialize_team("Group", [TeamMember(id="alice", name="Alice")])
    service.initialize_assignment("Only", "Do it")
    course = Course(
        id="architecture",
        name="Architecture",
        course_date=date(2026, 7, 17),
        teacher="Teacher",
        topic="Design",
        is_active=True,
    )
    from coursepilot.repositories import CourseRepository

    CourseRepository(data_root).add(
        course_id=course.id,
        name=course.name,
        course_date=course.course_date,
        teacher=course.teacher,
        topic=course.topic,
        active=True,
    )
    initial_context = service.context(course)
    output = MainAgentResult(
        intent=AgentKind.REVISION,
        invoked_agents=[AgentKind.ASSIGNMENT, AgentKind.REVIEW, AgentKind.REVISION],
        final_response="Revised",
        context=initial_context,
        assignment_output=AssignmentResult(
            task_understanding="Deliver a design",
            shared_answer="Draft",
            course_evidence=[],
            uncertainties=[],
        ),
        review_output=review(),
        revision_output=RevisionResult(
            mode=RevisionMode.CONSERVATIVE,
            source_version=1,
            result_version=2,
            revised_answer="Revised draft",
            changes=["Added alternatives"],
            unresolved_issues=[],
        ),
    )

    restored = service.apply_agent_output(course, output, "alice")

    assert restored.current_answer == "Revised draft"
    assert restored.answer_version == 2


def test_agent_output_transaction_rolls_back_answer_when_revision_has_no_review(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    repository = WorkspaceRepository(data_root)
    service = WorkspaceService(repository)
    service.initialize_team("Group", [TeamMember(id="alice", name="Alice")])
    service.initialize_assignment("Only", "Do it")
    course = Course(
        id="architecture",
        name="Architecture",
        course_date=date(2026, 7, 17),
        teacher="Teacher",
        topic="Design",
        is_active=True,
    )
    from coursepilot.repositories import CourseRepository

    CourseRepository(data_root).add(
        course_id=course.id,
        name=course.name,
        course_date=course.course_date,
        teacher=course.teacher,
        topic=course.topic,
        active=True,
    )
    output = MainAgentResult(
        intent=AgentKind.REVISION,
        invoked_agents=[AgentKind.REVISION],
        final_response="invalid partial workflow",
        context=service.context(course),
        assignment_output=AssignmentResult(
            task_understanding="Task",
            shared_answer="Must roll back",
            course_evidence=[],
            uncertainties=[],
        ),
        revision_output=RevisionResult(
            mode=RevisionMode.CONSERVATIVE,
            source_version=1,
            result_version=2,
            revised_answer="No review",
            changes=["Invalid"],
            unresolved_issues=[],
        ),
    )

    with pytest.raises(ValueError, match="requires a review"):
        service.apply_agent_output(course, output, "alice")

    assert repository.latest_answer() is None


def test_agent_output_for_a_stale_assignment_is_rejected(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    repository = WorkspaceRepository(data_root)
    service = WorkspaceService(repository)
    service.initialize_team("Group", [TeamMember(id="alice", name="Alice")])
    first = service.initialize_assignment("First", "Do first")
    course = Course(
        id="architecture",
        name="Architecture",
        course_date=date(2026, 7, 17),
        teacher="Teacher",
        topic="Design",
        is_active=True,
    )
    stale_context = service.context(course)
    second = service.create_assignment("assignment-2", "Second", "Do second")
    output = MainAgentResult(
        intent=AgentKind.ASSIGNMENT,
        invoked_agents=[AgentKind.ASSIGNMENT],
        final_response="Draft",
        context=stale_context,
        assignment_output=AssignmentResult(
            task_understanding="Task",
            shared_answer="Wrong target",
            course_evidence=[],
            uncertainties=[],
        ),
    )

    with pytest.raises(ValueError, match="does not match"):
        service.apply_agent_output(course, output, "alice")

    assert first.id != second.id
    assert repository.latest_answer(second.id) is None
