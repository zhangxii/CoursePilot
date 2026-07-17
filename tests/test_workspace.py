from datetime import date
from pathlib import Path

import pytest

from coursepilot.database import initialize_database
from coursepilot.models import (
    Course,
    DimensionScore,
    ReviewResult,
    RevisionMode,
    SourceRef,
    TeamMember,
)
from coursepilot.repositories import WorkspaceRepository
from coursepilot.services import WorkspaceService


def review() -> ReviewResult:
    source = SourceRef(
        material_id="m1",
        file_name="rubric.pdf",
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
    database = tmp_path / "business.db"
    initialize_database(database)
    service = WorkspaceService(WorkspaceRepository(database))
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

    restored = WorkspaceService(WorkspaceRepository(database))
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
    comparison = restored.compare_revision(revision, [])
    assert comparison.operated_by_member_id == "alice"
    assert comparison.resolved_issues == ["Missing alternatives"]


def test_invalid_revision_rolls_back_answer_and_revision_together(tmp_path: Path) -> None:
    database = tmp_path / "business.db"
    initialize_database(database)
    service = WorkspaceService(WorkspaceRepository(database))
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


def test_second_team_and_assignment_are_rejected(tmp_path: Path) -> None:
    database = tmp_path / "business.db"
    initialize_database(database)
    service = WorkspaceService(WorkspaceRepository(database))
    service.initialize_team("One", [TeamMember(id="alice", name="Alice")])
    service.initialize_assignment("Only assignment", "Do it")

    with pytest.raises(ValueError, match="one team"):
        service.initialize_team("Two", [TeamMember(id="bob", name="Bob")])
    with pytest.raises(ValueError, match="one assignment"):
        service.initialize_assignment("Second", "Not allowed")
