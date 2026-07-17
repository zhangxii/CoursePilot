from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pydantic import ValidationError

from coursepilot.file_store import FileDataStore, dump_yaml
from coursepilot.models import (
    AnswerSource,
    AssignmentUploadPurpose,
    CandidateDraft,
    CandidateStatus,
    DimensionScore,
    ReviewResult,
    RevisionMode,
    SourceRef,
    TeamMember,
)
from coursepilot.repositories import WorkspaceRepository
from coursepilot.services import (
    AdoptCandidateService,
    AssignmentArtifactService,
    CandidateDraftService,
    WorkspaceService,
)


def initialized_services(
    data_root: Path,
) -> tuple[WorkspaceService, AssignmentArtifactService]:
    workspace = WorkspaceService(WorkspaceRepository(data_root))
    workspace.initialize_team("Group", [TeamMember(id="alice", name="Alice")])
    workspace.initialize_assignment("Course report", "Submit a complete report")
    return workspace, AssignmentArtifactService(data_root, workspace)


def test_user_can_upload_a_markdown_initial_answer_and_restore_it(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    workspace, artifacts = initialized_services(data_root)

    imported = artifacts.import_assignment(
        file_name="my-draft.md",
        content=b"# My plan\n\nDetailed answer.",
        purpose=AssignmentUploadPurpose.INITIAL_VERSION,
        member_id="alice",
        version_note="My offline first draft",
    )

    assert imported.answer_version is not None
    assert imported.answer_version.version == 1
    assert imported.answer_version.source is AnswerSource.USER_UPLOAD
    assert imported.answer_version.version_note == "My offline first draft"
    assert imported.attachment.original_file_name == "my-draft.md"
    assert imported.attachment.normalized_content == "# My plan\n\nDetailed answer."
    assert imported.attachment.original_path.endswith("my-draft.md")
    assert (data_root / imported.attachment.original_path).read_bytes() == content_bytes(
        "# My plan\n\nDetailed answer."
    )

    restored_workspace = WorkspaceService(WorkspaceRepository(data_root))
    restored_artifacts = AssignmentArtifactService(data_root, restored_workspace)
    restored = restored_artifacts.get_answer_version(imported.answer_version.id)

    assert restored.content == "# My plan\n\nDetailed answer."
    assert restored.source is AnswerSource.USER_UPLOAD


def content_bytes(value: str) -> bytes:
    return value.encode("utf-8")


def test_offline_edit_creates_a_new_formal_version_without_overwriting_history(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    workspace, artifacts = initialized_services(data_root)
    first = artifacts.import_assignment(
        "draft.txt",
        content_bytes("Version one"),
        AssignmentUploadPurpose.INITIAL_VERSION,
        "alice",
        "Initial",
    )
    second = artifacts.import_assignment(
        "edited.txt",
        content_bytes("Version two"),
        AssignmentUploadPurpose.NEW_FORMAL_VERSION,
        "alice",
        "Edited offline",
    )
    reference = artifacts.import_assignment(
        "ideas.md",
        content_bytes("Ideas only"),
        AssignmentUploadPurpose.REFERENCE_ATTACHMENT,
        "alice",
        "Reference",
    )

    assert first.answer_version is not None
    assert second.answer_version is not None
    assert first.answer_version.version == 1
    assert second.answer_version.version == 2
    assert second.answer_version.based_on_version_id == first.answer_version.id
    assert artifacts.get_answer_version(first.answer_version.id).content == "Version one"
    assert workspace.latest_answer() == second.answer_version
    assert reference.answer_version is None

    with pytest.raises(ValueError, match="initial version"):
        artifacts.import_assignment(
            "wrong.txt",
            content_bytes("Must not overwrite"),
            AssignmentUploadPurpose.INITIAL_VERSION,
            "alice",
            "Wrong purpose",
        )


def test_docx_assignment_is_extracted_as_text_without_executing_embedded_content(
    tmp_path: Path,
) -> None:
    workspace, artifacts = initialized_services(tmp_path / "data")

    imported = artifacts.import_assignment(
        "report.docx",
        minimal_docx("Heading", "First paragraph", "Second paragraph"),
        AssignmentUploadPurpose.INITIAL_VERSION,
        "alice",
        "Word draft",
    )

    assert imported.answer_version is not None
    assert imported.answer_version.content == "Heading\n\nFirst paragraph\n\nSecond paragraph"


def minimal_docx(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>" for paragraph in paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def test_reviewed_candidate_requires_explicit_adoption_to_create_a_formal_version(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    workspace, artifacts = initialized_services(data_root)
    initial = artifacts.import_assignment(
        "draft.md",
        content_bytes("User version"),
        AssignmentUploadPurpose.INITIAL_VERSION,
        "alice",
        "User plan",
    )
    drafts = CandidateDraftService(data_root, workspace)
    adoption = AdoptCandidateService(drafts, workspace)

    candidate = drafts.create(
        "Agent candidate",
        "conversation-1",
        revision_mode=RevisionMode.CONSERVATIVE,
        change_summary="Improved structure",
        resolved_issues=["Weak structure"],
        unresolved_issues=["Confirm budget"],
    )

    assert initial.answer_version is not None
    assert workspace.latest_answer() == initial.answer_version
    assert candidate.status is CandidateStatus.DRAFT

    ready = drafts.complete_automatic_review(candidate.id, automatic_review())
    adopted = adoption.adopt(ready.id, "alice")

    assert adopted.version == 2
    assert adopted.content == "Agent candidate"
    assert adopted.source is AnswerSource.ADOPTED_CANDIDATE
    assert adopted.based_on_version_id == initial.answer_version.id
    assert adopted.adopted_candidate_id == candidate.id
    assert adopted.automatic_review_id == ready.automatic_review_id
    assert adopted.revision_mode is RevisionMode.CONSERVATIVE
    assert drafts.get(candidate.id).status is CandidateStatus.ADOPTED
    comparison = artifacts.compare_answer_versions(initial.answer_version.id, adopted.id)
    assert comparison.change_summary == "Improved structure"
    assert comparison.resolved_issues == ["Weak structure"]
    assert comparison.unresolved_issues == ["Confirm budget"]


def test_stale_candidate_cannot_overwrite_a_newer_user_version(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    workspace, artifacts = initialized_services(data_root)
    artifacts.import_assignment(
        "draft.md",
        content_bytes("Version one"),
        AssignmentUploadPurpose.INITIAL_VERSION,
        "alice",
        "Initial",
    )
    drafts = CandidateDraftService(data_root, workspace)
    adoption = AdoptCandidateService(drafts, workspace)
    candidate = drafts.create("Candidate based on v1", "conversation-1")
    drafts.complete_automatic_review(candidate.id, automatic_review())
    latest = artifacts.import_assignment(
        "offline.md",
        content_bytes("User version two"),
        AssignmentUploadPurpose.NEW_FORMAL_VERSION,
        "alice",
        "Offline change",
    )

    with pytest.raises(ValueError, match="base version is stale"):
        adoption.adopt(candidate.id, "alice")

    assert workspace.latest_answer() == latest.answer_version


def test_continuing_a_candidate_preserves_a_traceable_candidate_lineage(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    workspace, _ = initialized_services(data_root)
    drafts = CandidateDraftService(data_root, workspace)
    first = drafts.create("First candidate", "conversation-1")

    second = drafts.continue_from(first.id, "Improved candidate")

    restored_first = drafts.get(first.id)
    assert restored_first.status is CandidateStatus.SUPERSEDED
    assert restored_first.superseded_by_candidate_id == second.id
    assert second.derived_from_candidate_id == first.id
    assert second.base_answer_version_id == first.base_answer_version_id
    with pytest.raises(ValueError, match="draft candidate"):
        drafts.complete_automatic_review(first.id, automatic_review())


def test_candidate_comparison_shows_the_base_and_candidate_changes(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    workspace, artifacts = initialized_services(data_root)
    artifacts.import_assignment(
        "draft.txt",
        content_bytes("Title\nOld detail"),
        AssignmentUploadPurpose.INITIAL_VERSION,
        "alice",
        "Initial",
    )
    drafts = CandidateDraftService(data_root, workspace)
    candidate = drafts.create(
        "Title\nNew detail\nAdded line",
        "conversation-1",
        change_summary="Replaced detail and added evidence",
        resolved_issues=["Missing evidence"],
        unresolved_issues=["Confirm budget"],
    )

    comparison = drafts.compare_to_base(candidate.id)

    assert comparison.base_content == "Title\nOld detail"
    assert comparison.candidate_content == "Title\nNew detail\nAdded line"
    assert "-Old detail" in comparison.unified_diff
    assert "+New detail" in comparison.unified_diff
    assert "+Added line" in comparison.unified_diff
    assert comparison.change_summary == "Replaced detail and added evidence"
    assert comparison.resolved_issues == ["Missing evidence"]
    assert comparison.unresolved_issues == ["Confirm budget"]


def test_candidate_state_combinations_and_transitions_are_enforced(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        CandidateDraft(
            id="candidate-1",
            assignment_id="assignment-1",
            conversation_id="conversation-1",
            content="Draft",
            status=CandidateStatus.ADOPTED,
        )
    with pytest.raises(ValidationError):
        CandidateDraft(
            id="candidate-2",
            assignment_id="assignment-1",
            conversation_id="conversation-1",
            content="Draft",
            status=CandidateStatus.READY_FOR_ADOPTION,
            automatic_review_id=" ",
        )

    data_root = tmp_path / "data"
    workspace, _ = initialized_services(data_root)
    drafts = CandidateDraftService(data_root, workspace)
    adoption = AdoptCandidateService(drafts, workspace)
    candidate = drafts.create("Draft", "conversation-1")
    with pytest.raises(ValueError, match="not ready"):
        adoption.adopt(candidate.id, "alice")

    discarded = drafts.discard(candidate.id)
    assert discarded.status is CandidateStatus.DISCARDED
    with pytest.raises(ValueError, match="active candidate"):
        drafts.continue_from(discarded.id, "Cannot continue")


def test_assignment_upload_validates_size_type_encoding_and_safe_name(tmp_path: Path) -> None:
    workspace, artifacts = initialized_services(tmp_path / "data")
    invalid_cases = [
        ("empty.md", b"", "must not be empty"),
        ("binary.txt", b"\xff\xfe", "must be UTF-8"),
        ("answer.pdf", b"pdf", "must be .md, .txt, or .docx"),
        ("broken.docx", b"not a zip", "DOCX is invalid"),
        ("CON.txt", b"reserved", "file name is reserved"),
        ("../escape.md", b"escape", "file name is invalid"),
        (f"{'a' * 129}.md", b"long", "file name is invalid"),
        ("huge.md", b"x" * 101, "exceeds 100 bytes"),
    ]
    limited = AssignmentArtifactService(tmp_path / "data", workspace, max_upload_bytes=100)
    for file_name, content, message in invalid_cases:
        with pytest.raises(ValueError, match=message):
            limited.import_assignment(
                file_name,
                content,
                AssignmentUploadPurpose.REFERENCE_ATTACHMENT,
                "alice",
                "Reference",
            )

    with pytest.raises(ValueError, match="document text exceeds 10 MB"):
        artifacts.import_assignment(
            "expanded.docx",
            minimal_docx("x" * (10 * 1024 * 1024)),
            AssignmentUploadPurpose.REFERENCE_ATTACHMENT,
            "alice",
            "Expanded",
        )


def test_attachment_and_formal_version_history_can_be_listed_after_restart(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    workspace, artifacts = initialized_services(data_root)
    artifacts.import_assignment(
        "v1.txt",
        b"First",
        AssignmentUploadPurpose.INITIAL_VERSION,
        "alice",
        "First",
    )
    artifacts.import_assignment(
        "v2.txt",
        b"Second",
        AssignmentUploadPurpose.NEW_FORMAL_VERSION,
        "alice",
        "Second",
    )
    artifacts.import_assignment(
        "notes.txt",
        b"Reference",
        AssignmentUploadPurpose.REFERENCE_ATTACHMENT,
        "alice",
        "Notes",
    )

    restored_workspace = WorkspaceService(WorkspaceRepository(data_root))
    restored = AssignmentArtifactService(data_root, restored_workspace)

    versions = restored.list_answer_versions()
    attachments = restored.list_attachments()
    comparison = restored.compare_answer_versions(versions[0].id, versions[1].id)
    assert [item.content for item in versions] == ["First", "Second"]
    assert [item.original_file_name for item in attachments] == [
        "notes.txt",
        "v1.txt",
        "v2.txt",
    ]
    assert all(item.normalized_content for item in attachments)
    assert [(data_root / item.original_path).read_bytes() for item in attachments] == [
        b"Reference",
        b"First",
        b"Second",
    ]
    assert "-First" in comparison.unified_diff
    assert "+Second" in comparison.unified_diff


def test_assignment_upload_rolls_back_every_file_when_atomic_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "data"
    workspace, artifacts = initialized_services(data_root)
    original_apply = FileDataStore._apply_batch

    def fail_after_writes(store: FileDataStore, payload: object) -> None:
        original_apply(store, payload)
        raise OSError("simulated commit failure")

    monkeypatch.setattr(FileDataStore, "_apply_batch", fail_after_writes)
    with pytest.raises(OSError, match="simulated commit failure"):
        artifacts.import_assignment(
            "draft.md",
            b"Must roll back",
            AssignmentUploadPurpose.INITIAL_VERSION,
            "alice",
            "Initial",
        )

    assert workspace.latest_answer() is None
    assert not [
        path
        for path in data_root.glob("assignments/assignment-1/attachments/**/*")
        if path.is_file()
    ]


def test_candidate_adoption_rolls_back_version_and_state_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "data"
    workspace, artifacts = initialized_services(data_root)
    initial = artifacts.import_assignment(
        "draft.md",
        b"Formal v1",
        AssignmentUploadPurpose.INITIAL_VERSION,
        "alice",
        "Initial",
    )
    drafts = CandidateDraftService(data_root, workspace)
    adoption = AdoptCandidateService(drafts, workspace)
    candidate = drafts.create("Candidate v2", "conversation-1")
    ready = drafts.complete_automatic_review(candidate.id, automatic_review())
    original_apply = FileDataStore._apply_batch

    def fail_after_writes(store: FileDataStore, payload: object) -> None:
        original_apply(store, payload)
        raise OSError("simulated adoption failure")

    monkeypatch.setattr(FileDataStore, "_apply_batch", fail_after_writes)
    with pytest.raises(OSError, match="simulated adoption failure"):
        adoption.adopt(ready.id, "alice")

    assert workspace.latest_answer() == initial.answer_version
    assert drafts.get(ready.id).status is CandidateStatus.READY_FOR_ADOPTION


def test_pending_mixed_file_transaction_is_rolled_back_on_restart(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    store = FileDataStore(data_root)
    store.write_bytes("assignments/a/attachments/x/original/draft.docx", b"partial")
    store.write_text("assignments/a/answers/0001.md", "partial answer")
    store.write_text(
        ".pending-batch.yaml",
        dump_yaml(
            {
                "entries": {
                    "assignments/a/attachments/x/original/draft.docx": {
                        "new": b"partial",
                        "existed": False,
                        "old": None,
                    },
                    "assignments/a/answers/0001.md": {
                        "new": "partial answer",
                        "existed": False,
                        "old": None,
                    },
                }
            }
        ),
    )

    restored = FileDataStore(data_root)

    assert not restored.exists("assignments/a/attachments/x/original/draft.docx")
    assert not restored.exists("assignments/a/answers/0001.md")
    assert not restored.exists(".pending-batch.yaml")


def automatic_review() -> ReviewResult:
    source = SourceRef(
        material_id="material-1",
        file_name="rubric.md",
        course_id="course-1",
        page_or_section="rubric",
        excerpt="The answer must explain tradeoffs.",
    )
    return ReviewResult(
        total_score=90,
        dimension_scores=[
            DimensionScore(
                dimension="quality",
                score=90,
                max_score=100,
                deduction=10,
                location="whole answer",
                evidence=[source],
                reason="One uncertainty remains",
                revision_advice="Confirm the budget",
            )
        ],
        strengths=["Clear structure"],
        critical_issues=["Confirm the budget"],
        likely_teacher_questions=["What is the final budget?"],
        revision_priorities=["Confirm the budget"],
    )
