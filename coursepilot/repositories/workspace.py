"""File-backed persistence for one team and multiple assignment aggregates."""

import hashlib
import re
import threading
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from coursepilot.file_store import FileDataStore, dump_yaml, parse_front_matter, render_front_matter
from coursepilot.models import (
    AnswerComparison,
    AnswerRecord,
    AnswerSource,
    Assignment,
    AssignmentUploadPurpose,
    AttachmentPurpose,
    AttachmentRecord,
    AutomaticReviewRecord,
    CandidateDraft,
    CandidateStatus,
    ImportedAssignment,
    MainAgentResult,
    NotesResult,
    ReviewRecord,
    ReviewResult,
    RevisionMode,
    RevisionRecord,
    Team,
    TeamMember,
)


class AssignmentIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_assignment_id: str | None
    assignment_ids: list[str]


class WorkspaceRepository:
    _lock = threading.RLock()

    def __init__(self, data_root: str | Path) -> None:
        self._store = FileDataStore(Path(data_root))
        self._migrate_legacy_assignment()

    def initialize_team(self, name: str, members: list[TeamMember]) -> Team:
        with self._lock:
            if self._store.exists("workspace.yaml"):
                raise ValueError("only one team is supported")
            team = Team(name=name, members=members)
            self._store.write_yaml("workspace.yaml", team.model_dump(mode="json"))
            return team

    def get_team(self) -> Team:
        data = self._store.read_yaml("workspace.yaml")
        if data is None:
            raise KeyError("main_team")
        return Team.model_validate(data)

    def initialize_assignment(
        self, title: str, requirements: str, rubric: str | None
    ) -> Assignment:
        return self.create_assignment("assignment-1", title, requirements, rubric)

    def create_assignment(
        self,
        assignment_id: str,
        title: str,
        requirements: str,
        rubric: str | None = None,
    ) -> Assignment:
        self._validate_assignment_id(assignment_id)
        assignment = Assignment(
            id=assignment_id, title=title, requirements=requirements, rubric=rubric
        )
        with self._lock:
            path = self._assignment_path(assignment_id)
            if self._store.exists(path):
                raise ValueError(f"assignment already exists: {assignment_id}")
            index = self._assignment_index()
            index.assignment_ids.append(assignment_id)
            index.active_assignment_id = assignment_id
            self._store.write_batch(
                {
                    path: self._assignment_document(assignment),
                    "assignments/assignment-index.yaml": dump_yaml(index.model_dump(mode="json")),
                }
            )
            return assignment

    def list_assignments(self) -> list[Assignment]:
        return [self.get_assignment(item) for item in self._assignment_index().assignment_ids]

    def get_assignment(self, assignment_id: str | None = None) -> Assignment:
        selected = assignment_id or self._active_assignment_id()
        metadata, body = parse_front_matter(self._store.read_text(self._assignment_path(selected)))
        return Assignment(
            id=selected,
            title=metadata["title"],
            requirements=body.strip(),
            rubric=metadata.get("rubric"),
        )

    def update_assignment(
        self,
        assignment_id: str,
        title: str,
        requirements: str,
        rubric: str | None,
    ) -> Assignment:
        self.get_assignment(assignment_id)
        assignment = Assignment(
            id=assignment_id, title=title, requirements=requirements, rubric=rubric
        )
        self._write_assignment(assignment)
        return assignment

    def activate_assignment(self, assignment_id: str) -> Assignment:
        with self._lock:
            self.get_assignment(assignment_id)
            index = self._assignment_index()
            index.active_assignment_id = assignment_id
            self._store.write_yaml(
                "assignments/assignment-index.yaml", index.model_dump(mode="json")
            )
        return self.get_assignment(assignment_id)

    def get_answer(self, answer_id: str) -> AnswerRecord:
        for path in self._store.glob("assignments/*/answers/*.md"):
            metadata, body = parse_front_matter(path.read_text(encoding="utf-8"))
            if metadata.get("id") == answer_id:
                return AnswerRecord(
                    id=answer_id,
                    assignment_id=metadata["assignment_id"],
                    version=metadata["version"],
                    content=body.strip(),
                    operated_by_member_id=metadata["operated_by_member_id"],
                    source=metadata.get("source", AnswerSource.LEGACY),
                    based_on_version_id=metadata.get("based_on_version_id"),
                    source_attachment_id=metadata.get("source_attachment_id"),
                    adopted_candidate_id=metadata.get("adopted_candidate_id"),
                    automatic_review_id=metadata.get("automatic_review_id"),
                    revision_mode=metadata.get("revision_mode"),
                    version_note=metadata.get("version_note"),
                )
        raise KeyError(answer_id)

    def latest_answer(self, assignment_id: str | None = None) -> AnswerRecord | None:
        selected = assignment_id or self._active_assignment_id()
        paths = self._store.glob(f"assignments/{selected}/answers/*.md")
        if not paths:
            return None
        metadata, _ = parse_front_matter(paths[-1].read_text(encoding="utf-8"))
        return self.get_answer(str(metadata["id"]))

    def list_answers(self, assignment_id: str | None = None) -> list[AnswerRecord]:
        selected = assignment_id or self._active_assignment_id()
        answers = []
        for path in self._store.glob(f"assignments/{selected}/answers/*.md"):
            metadata, _ = parse_front_matter(path.read_text(encoding="utf-8"))
            answers.append(self.get_answer(str(metadata["id"])))
        return answers

    def import_assignment_artifact(
        self,
        *,
        file_name: str,
        safe_name: str,
        original: bytes,
        normalized: str,
        purpose: AssignmentUploadPurpose,
        member_id: str,
        version_note: str,
    ) -> ImportedAssignment:
        with self._lock:
            selected = self._active_assignment_id()
            current = self.latest_answer(selected)
            if purpose is AssignmentUploadPurpose.INITIAL_VERSION and current is not None:
                raise ValueError("initial version requires an assignment without a formal answer")
            if purpose is AssignmentUploadPurpose.NEW_FORMAL_VERSION and current is None:
                raise ValueError("new formal version requires an existing formal answer")
            if (
                purpose is not AssignmentUploadPurpose.REFERENCE_ATTACHMENT
                and not version_note.strip()
            ):
                raise ValueError("formal assignment upload requires a version note")

            attachment_id = str(uuid4())
            base = f"assignments/{selected}/attachments/{attachment_id}"
            attachment = AttachmentRecord(
                id=attachment_id,
                assignment_id=selected,
                purpose=(
                    AttachmentPurpose.ASSIGNMENT_REFERENCE
                    if purpose is AssignmentUploadPurpose.REFERENCE_ATTACHMENT
                    else AttachmentPurpose.ASSIGNMENT_VERSION
                ),
                original_file_name=file_name,
                original_path=f"{base}/original/{safe_name}",
                normalized_path=f"{base}/normalized.md",
                normalized_content=normalized,
                content_hash=hashlib.sha256(original).hexdigest(),
            )
            documents: dict[str, str | bytes] = {
                attachment.original_path: original,
                attachment.normalized_path: normalized,
                f"{base}/attachment.yaml": dump_yaml(
                    attachment.model_dump(mode="json", exclude={"normalized_content"})
                ),
            }
            answer = None
            if purpose is not AssignmentUploadPurpose.REFERENCE_ATTACHMENT:
                version = 1 if current is None else current.version + 1
                answer, answer_document = self._new_answer(
                    normalized,
                    member_id,
                    version,
                    selected,
                    source=AnswerSource.USER_UPLOAD,
                    based_on_version_id=None if current is None else current.id,
                    source_attachment_id=attachment.id,
                    version_note=version_note,
                )
                documents[self._answer_path(selected, version)] = answer_document
            self._store.write_batch(documents)
            return ImportedAssignment(attachment=attachment, answer_version=answer)

    def list_attachments(self, assignment_id: str | None = None) -> list[AttachmentRecord]:
        selected = assignment_id or self._active_assignment_id()
        records = []
        for path in self._store.glob(f"assignments/{selected}/attachments/*/attachment.yaml"):
            data = self._store.read_yaml(path.relative_to(self._store.root))
            normalized = self._store.read_text(data["normalized_path"])
            records.append(
                AttachmentRecord.model_validate({**data, "normalized_content": normalized})
            )
        return sorted(records, key=lambda item: item.original_file_name)

    def create_candidate(
        self,
        content: str,
        conversation_id: str,
        assignment_id: str | None = None,
        *,
        base_answer_version_id: str | None = None,
        derived_from_candidate_id: str | None = None,
        change_summary: str = "",
        resolved_issues: list[str] | None = None,
        unresolved_issues: list[str] | None = None,
        revision_mode: RevisionMode | None = None,
    ) -> CandidateDraft:
        with self._lock:
            selected = assignment_id or self._active_assignment_id()
            if base_answer_version_id is None and derived_from_candidate_id is None:
                current = self.latest_answer(selected)
                base_answer_version_id = None if current is None else current.id
            candidate = CandidateDraft(
                id=str(uuid4()),
                assignment_id=selected,
                conversation_id=conversation_id,
                base_answer_version_id=base_answer_version_id,
                derived_from_candidate_id=derived_from_candidate_id,
                content=content,
                change_summary=change_summary,
                resolved_issues=resolved_issues or [],
                unresolved_issues=unresolved_issues or [],
                revision_mode=revision_mode,
            )
            self._store.write_text(
                self._candidate_path(selected, candidate.id),
                self._candidate_document(candidate),
            )
            return candidate

    def get_candidate(self, candidate_id: str) -> CandidateDraft:
        matches = self._store.glob(f"assignments/*/candidates/{candidate_id}.md")
        if not matches:
            raise KeyError(candidate_id)
        metadata, body = parse_front_matter(matches[0].read_text(encoding="utf-8"))
        return CandidateDraft.model_validate({**metadata, "content": body.strip()})

    def list_candidates(self, assignment_id: str | None = None) -> list[CandidateDraft]:
        selected = assignment_id or self._active_assignment_id()
        candidates = []
        for path in self._store.glob(f"assignments/{selected}/candidates/*.md"):
            metadata, _ = parse_front_matter(path.read_text(encoding="utf-8"))
            candidates.append(self.get_candidate(str(metadata["id"])))
        return candidates

    def complete_candidate_review(self, candidate_id: str, result: ReviewResult) -> CandidateDraft:
        return self.complete_candidate_review_cycle(candidate_id, result)

    def complete_candidate_review_cycle(
        self,
        candidate_id: str,
        first_review: ReviewResult,
        *,
        corrected_content: str | None = None,
        final_review: ReviewResult | None = None,
    ) -> CandidateDraft:
        with self._lock:
            candidate = self.get_candidate(candidate_id)
            if candidate.status is not CandidateStatus.DRAFT:
                raise ValueError("only a draft candidate can become ready")
            if (corrected_content is None) != (final_review is None):
                raise ValueError("correction and final review must be provided together")
            first = AutomaticReviewRecord(
                id=str(uuid4()), candidate_id=candidate.id, result=first_review
            )
            target = candidate
            documents: dict[str, str | bytes] = {
                self._candidate_review_path(candidate.assignment_id, first.id): dump_yaml(
                    first.model_dump(mode="json")
                )
            }
            if corrected_content is not None and final_review is not None:
                target = CandidateDraft(
                    id=str(uuid4()),
                    assignment_id=candidate.assignment_id,
                    conversation_id=candidate.conversation_id,
                    base_answer_version_id=candidate.base_answer_version_id,
                    derived_from_candidate_id=candidate.id,
                    content=corrected_content,
                    revision_mode=candidate.revision_mode,
                    review_fixed_issues=[
                        issue
                        for issue in first_review.critical_issues
                        if issue not in final_review.critical_issues
                    ],
                    review_pending_issues=final_review.critical_issues,
                )
                superseded = CandidateDraft.model_validate(
                    {
                        **candidate.model_dump(mode="json"),
                        "status": CandidateStatus.SUPERSEDED,
                        "superseded_by_candidate_id": target.id,
                    }
                )
                documents[self._candidate_path(candidate.assignment_id, candidate.id)] = (
                    self._candidate_document(superseded)
                )
                final = AutomaticReviewRecord(
                    id=str(uuid4()), candidate_id=target.id, result=final_review
                )
                documents[self._candidate_review_path(target.assignment_id, final.id)] = dump_yaml(
                    final.model_dump(mode="json")
                )
                review_id = final.id
            else:
                review_id = first.id
            ready = CandidateDraft.model_validate(
                {
                    **target.model_dump(mode="json"),
                    "status": CandidateStatus.READY_FOR_ADOPTION,
                    "automatic_review_id": review_id,
                    "review_pending_issues": (
                        first_review.critical_issues
                        if final_review is None
                        else target.review_pending_issues
                    ),
                }
            )
            documents[self._candidate_path(ready.assignment_id, ready.id)] = (
                self._candidate_document(ready)
            )
            self._store.write_batch(documents)
            return ready

    def get_candidate_review(self, review_id: str) -> AutomaticReviewRecord:
        matches = self._store.glob(f"assignments/*/candidate-reviews/{review_id}.yaml")
        if not matches:
            raise KeyError(review_id)
        return AutomaticReviewRecord.model_validate(
            self._store.read_yaml(matches[0].relative_to(self._store.root))
        )

    def discard_candidate(self, candidate_id: str) -> CandidateDraft:
        with self._lock:
            candidate = self.get_candidate(candidate_id)
            if candidate.status not in {
                CandidateStatus.DRAFT,
                CandidateStatus.READY_FOR_ADOPTION,
            }:
                raise ValueError("only an active candidate can be discarded")
            discarded = CandidateDraft.model_validate(
                {
                    **candidate.model_dump(mode="json"),
                    "status": CandidateStatus.DISCARDED,
                    "automatic_review_id": None,
                }
            )
            self._store.write_text(
                self._candidate_path(discarded.assignment_id, discarded.id),
                self._candidate_document(discarded),
            )
            return discarded

    def continue_candidate(self, candidate_id: str, content: str) -> CandidateDraft:
        with self._lock:
            source = self.get_candidate(candidate_id)
            if source.status not in {
                CandidateStatus.DRAFT,
                CandidateStatus.READY_FOR_ADOPTION,
            }:
                raise ValueError("only an active candidate can be continued")
            child = CandidateDraft(
                id=str(uuid4()),
                assignment_id=source.assignment_id,
                conversation_id=source.conversation_id,
                base_answer_version_id=source.base_answer_version_id,
                derived_from_candidate_id=source.id,
                content=content,
            )
            superseded = CandidateDraft.model_validate(
                {
                    **source.model_dump(mode="json"),
                    "status": CandidateStatus.SUPERSEDED,
                    "superseded_by_candidate_id": child.id,
                    "automatic_review_id": None,
                }
            )
            self._store.write_batch(
                {
                    self._candidate_path(source.assignment_id, source.id): (
                        self._candidate_document(superseded)
                    ),
                    self._candidate_path(child.assignment_id, child.id): (
                        self._candidate_document(child)
                    ),
                }
            )
            return child

    def adopt_candidate(self, candidate_id: str, member_id: str) -> AnswerRecord:
        with self._lock:
            candidate = self.get_candidate(candidate_id)
            if candidate.status is not CandidateStatus.READY_FOR_ADOPTION:
                raise ValueError("candidate is not ready for adoption")
            if candidate.automatic_review_id is None:
                raise ValueError("candidate requires an automatic review")
            review = self.get_candidate_review(candidate.automatic_review_id)
            if review.candidate_id != candidate.id:
                raise ValueError("automatic review does not belong to candidate")
            current = self.latest_answer(candidate.assignment_id)
            current_id = None if current is None else current.id
            if current_id != candidate.base_answer_version_id:
                raise ValueError("candidate base version is stale")
            version = 1 if current is None else current.version + 1
            answer, answer_document = self._new_answer(
                candidate.content,
                member_id,
                version,
                candidate.assignment_id,
                source=AnswerSource.ADOPTED_CANDIDATE,
                based_on_version_id=candidate.base_answer_version_id,
                adopted_candidate_id=candidate.id,
                automatic_review_id=candidate.automatic_review_id,
                revision_mode=candidate.revision_mode,
                version_note="Adopted reviewed candidate",
            )
            adopted = CandidateDraft.model_validate(
                {**candidate.model_dump(mode="json"), "status": CandidateStatus.ADOPTED}
            )
            self._store.write_batch(
                {
                    self._answer_path(candidate.assignment_id, version): answer_document,
                    self._candidate_path(candidate.assignment_id, candidate.id): (
                        self._candidate_document(adopted)
                    ),
                }
            )
            return answer

    def add_review(self, answer_id: str, result: ReviewResult) -> ReviewRecord:
        answer = self.get_answer(answer_id)
        review = ReviewRecord(id=str(uuid4()), answer_id=answer_id, result=result)
        self._store.write_yaml(
            f"assignments/{answer.assignment_id}/reviews/{review.id}.yaml",
            review.model_dump(mode="json"),
        )
        return review

    def latest_review(
        self, answer_id: str, assignment_id: str | None = None
    ) -> ReviewRecord | None:
        matches = []
        selected = assignment_id or self.get_answer(answer_id).assignment_id
        for path in self._store.glob(f"assignments/{selected}/reviews/*.yaml"):
            review = ReviewRecord.model_validate(
                self._store.read_yaml(path.relative_to(self._store.root))
            )
            if review.answer_id == answer_id:
                matches.append((path.stat().st_mtime_ns, review))
        return None if not matches else max(matches, key=lambda item: item[0])[1]

    def latest_revision(self, assignment_id: str | None = None) -> RevisionRecord | None:
        selected = assignment_id or self._active_assignment_id()
        paths = self._store.glob(f"assignments/{selected}/revisions/*.yaml")
        return (
            None
            if not paths
            else RevisionRecord.model_validate(
                self._store.read_yaml(paths[-1].relative_to(self._store.root))
            )
        )

    def compare_revision(self, revision: RevisionRecord) -> AnswerComparison:
        source = self.get_answer(revision.source_answer_id)
        result = self.get_answer(revision.result_answer_id)
        review = self.latest_review(source.id)
        critical = [] if review is None else review.result.critical_issues
        unresolved = [item for item in critical if item in revision.unresolved_issues]
        return AnswerComparison(
            source_version=source.version,
            result_version=result.version,
            operated_by_member_id=result.operated_by_member_id,
            change_summary=revision.change_summary,
            resolved_issues=[item for item in critical if item not in unresolved],
            unresolved_issues=unresolved,
        )

    def save_notes(self, course_id: str, result: NotesResult) -> str:
        note_id = str(uuid4())
        self._store.write_yaml(
            f"courses/{course_id}/notes/{note_id}.yaml", result.model_dump(mode="json")
        )
        return note_id

    def get_notes(self, note_id: str) -> NotesResult:
        matches = self._store.glob(f"courses/*/notes/{note_id}.yaml")
        if not matches:
            raise KeyError(note_id)
        return NotesResult.model_validate(
            self._store.read_yaml(matches[0].relative_to(self._store.root))
        )

    def apply_agent_output(
        self,
        course_id: str,
        output: MainAgentResult,
        member_id: str,
    ) -> CandidateDraft | None:
        with self._lock:
            selected = self._active_assignment_id()
            documents: dict[str, str | bytes] = {}
            base = (
                None
                if output.context.base_answer_version_id is None
                else self.get_answer(output.context.base_answer_version_id)
            )
            if base is not None and base.assignment_id != selected:
                raise ValueError("agent output base version does not match active assignment")
            if output.notes_output is not None:
                note_id = str(uuid4())
                documents[f"courses/{course_id}/notes/{note_id}.yaml"] = dump_yaml(
                    output.notes_output.model_dump(mode="json")
                )
            candidate_content = None
            created_candidate = None
            change_summary = ""
            unresolved_issues: list[str] = []
            if output.revision_output is not None:
                persisted_review = None if base is None else self.latest_review(base.id, selected)
                if output.review_output is None and persisted_review is None:
                    raise ValueError("revision requires a review for the current answer")
                candidate_content = output.revision_output.revised_answer
                change_summary = "；".join(output.revision_output.changes)
                unresolved_issues = output.revision_output.unresolved_issues
            elif output.assignment_output is not None:
                candidate_content = output.assignment_output.shared_answer

            if candidate_content is not None:
                candidate_id = str(uuid4())
                candidate = CandidateDraft(
                    id=candidate_id,
                    assignment_id=selected,
                    conversation_id=output.context.conversation_id,
                    base_answer_version_id=None if base is None else base.id,
                    content=candidate_content,
                    status=CandidateStatus.DRAFT,
                    revision_mode=(
                        None if output.revision_output is None else output.revision_output.mode
                    ),
                    change_summary=change_summary,
                    unresolved_issues=unresolved_issues,
                )
                documents[self._candidate_path(selected, candidate.id)] = self._candidate_document(
                    candidate
                )
                created_candidate = candidate
                if output.review_output is not None and base is not None:
                    formal_review = ReviewRecord(
                        id=str(uuid4()), answer_id=base.id, result=output.review_output
                    )
                    documents[f"assignments/{selected}/reviews/{formal_review.id}.yaml"] = (
                        dump_yaml(formal_review.model_dump(mode="json"))
                    )
            elif output.review_output is not None:
                if base is None:
                    raise ValueError("review requires a formal answer")
                formal_review = ReviewRecord(
                    id=str(uuid4()), answer_id=base.id, result=output.review_output
                )
                documents[f"assignments/{selected}/reviews/{formal_review.id}.yaml"] = dump_yaml(
                    formal_review.model_dump(mode="json")
                )
            self._store.write_batch(documents)
            return created_candidate

    def _write_assignment(self, assignment: Assignment) -> None:
        self._store.write_text(
            self._assignment_path(assignment.id), self._assignment_document(assignment)
        )

    @staticmethod
    def _assignment_document(assignment: Assignment) -> str:
        return render_front_matter(
            {"id": assignment.id, "title": assignment.title, "rubric": assignment.rubric},
            assignment.requirements,
        )

    @staticmethod
    def _new_answer(
        content: str,
        member_id: str,
        version: int,
        assignment_id: str,
        *,
        source: AnswerSource = AnswerSource.LEGACY,
        based_on_version_id: str | None = None,
        source_attachment_id: str | None = None,
        adopted_candidate_id: str | None = None,
        automatic_review_id: str | None = None,
        revision_mode: RevisionMode | None = None,
        version_note: str | None = None,
    ) -> tuple[AnswerRecord, str]:
        answer = AnswerRecord(
            id=str(uuid4()),
            assignment_id=assignment_id,
            version=version,
            content=content,
            operated_by_member_id=member_id,
            source=source,
            based_on_version_id=based_on_version_id,
            source_attachment_id=source_attachment_id,
            adopted_candidate_id=adopted_candidate_id,
            automatic_review_id=automatic_review_id,
            revision_mode=revision_mode,
            version_note=version_note,
        )
        document = render_front_matter(
            {
                "id": answer.id,
                "assignment_id": assignment_id,
                "version": answer.version,
                "operated_by_member_id": member_id,
                "source": answer.source.value,
                "based_on_version_id": based_on_version_id,
                "source_attachment_id": source_attachment_id,
                "adopted_candidate_id": adopted_candidate_id,
                "automatic_review_id": automatic_review_id,
                "revision_mode": None if revision_mode is None else revision_mode.value,
                "version_note": version_note,
            },
            content,
        )
        return answer, document

    @staticmethod
    def _answer_path(assignment_id: str, version: int) -> str:
        return f"assignments/{assignment_id}/answers/{version:04d}.md"

    @staticmethod
    def _candidate_path(assignment_id: str, candidate_id: str) -> str:
        return f"assignments/{assignment_id}/candidates/{candidate_id}.md"

    @staticmethod
    def _candidate_review_path(assignment_id: str, review_id: str) -> str:
        return f"assignments/{assignment_id}/candidate-reviews/{review_id}.yaml"

    @staticmethod
    def _candidate_document(candidate: CandidateDraft) -> str:
        metadata = candidate.model_dump(mode="json", exclude={"content"})
        return render_front_matter(metadata, candidate.content)

    @staticmethod
    def candidate_document(candidate: CandidateDraft) -> str:
        return WorkspaceRepository._candidate_document(candidate)

    @staticmethod
    def candidate_storage_path(assignment_id: str, candidate_id: str) -> str:
        return WorkspaceRepository._candidate_path(assignment_id, candidate_id)

    @staticmethod
    def candidate_review_storage_path(assignment_id: str, review_id: str) -> str:
        return WorkspaceRepository._candidate_review_path(assignment_id, review_id)

    @staticmethod
    def _assignment_path(assignment_id: str) -> str:
        return f"assignments/{assignment_id}/assignment.md"

    @staticmethod
    def _validate_assignment_id(assignment_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", assignment_id):
            raise ValueError(
                "assignment_id may contain only letters, numbers, underscore and hyphen"
            )

    def _assignment_index(self) -> AssignmentIndex:
        return AssignmentIndex.model_validate(
            self._store.read_yaml(
                "assignments/assignment-index.yaml",
                {"active_assignment_id": None, "assignment_ids": []},
            )
        )

    def _active_assignment_id(self) -> str:
        active = self._assignment_index().active_assignment_id
        if active is None:
            raise KeyError("active_assignment")
        return active

    def _migrate_legacy_assignment(self) -> None:
        legacy = "assignment/assignment.md"
        if self._store.exists("assignments/assignment-index.yaml") or not self._store.exists(
            legacy
        ):
            return
        assignment_id = "assignment-1"
        assignment_metadata, assignment_body = parse_front_matter(self._store.read_text(legacy))
        assignment_metadata["id"] = assignment_id
        documents = {
            self._assignment_path(assignment_id): render_front_matter(
                assignment_metadata, assignment_body
            ),
            "assignments/assignment-index.yaml": dump_yaml(
                {
                    "active_assignment_id": assignment_id,
                    "assignment_ids": [assignment_id],
                }
            ),
        }
        for category, extension in (
            ("answers", "md"),
            ("reviews", "yaml"),
            ("revisions", "yaml"),
        ):
            for path in self._store.glob(f"assignment/{category}/*.{extension}"):
                content = path.read_text(encoding="utf-8")
                if category == "answers":
                    metadata, body = parse_front_matter(content)
                    metadata["assignment_id"] = assignment_id
                    content = render_front_matter(metadata, body)
                documents[f"assignments/{assignment_id}/{category}/{path.name}"] = content
        self._store.write_batch(documents)
