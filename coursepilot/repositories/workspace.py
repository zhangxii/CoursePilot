"""File-backed persistence for the singleton team and assignment lifecycle."""

import threading
from pathlib import Path
from uuid import uuid4

from coursepilot.file_store import FileDataStore, dump_yaml, parse_front_matter, render_front_matter
from coursepilot.models import (
    AnswerComparison,
    AnswerRecord,
    Assignment,
    MainAgentResult,
    NotesResult,
    ReviewRecord,
    ReviewResult,
    RevisionMode,
    RevisionRecord,
    Team,
    TeamMember,
)


class WorkspaceRepository:
    _lock = threading.RLock()

    def __init__(self, data_root: str | Path) -> None:
        self._store = FileDataStore(Path(data_root))

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
        with self._lock:
            if self._store.exists("assignment/assignment.md"):
                raise ValueError("only one assignment is supported")
            assignment = Assignment(title=title, requirements=requirements, rubric=rubric)
            self._write_assignment(assignment)
            return assignment

    def get_assignment(self) -> Assignment:
        if not self._store.exists("assignment/assignment.md"):
            raise KeyError("main_assignment")
        metadata, body = parse_front_matter(self._store.read_text("assignment/assignment.md"))
        return Assignment(
            title=metadata["title"], requirements=body.strip(), rubric=metadata.get("rubric")
        )

    def update_assignment(self, title: str, requirements: str, rubric: str | None) -> Assignment:
        self.get_assignment()
        assignment = Assignment(title=title, requirements=requirements, rubric=rubric)
        self._write_assignment(assignment)
        return assignment

    def add_answer(self, content: str, member_id: str) -> AnswerRecord:
        with self._lock:
            latest = self.latest_answer()
            version = 1 if latest is None else latest.version + 1
            answer, document = self._new_answer(content, member_id, version)
            self._store.write_text(self._answer_path(version), document)
            return answer

    def get_answer(self, answer_id: str) -> AnswerRecord:
        for path in self._store.glob("assignment/answers/*.md"):
            metadata, body = parse_front_matter(path.read_text(encoding="utf-8"))
            if metadata.get("id") == answer_id:
                return AnswerRecord(
                    id=answer_id,
                    version=metadata["version"],
                    content=body.strip(),
                    operated_by_member_id=metadata["operated_by_member_id"],
                )
        raise KeyError(answer_id)

    def latest_answer(self) -> AnswerRecord | None:
        paths = self._store.glob("assignment/answers/*.md")
        if not paths:
            return None
        metadata, _ = parse_front_matter(paths[-1].read_text(encoding="utf-8"))
        return self.get_answer(str(metadata["id"]))

    def add_review(self, answer_id: str, result: ReviewResult) -> ReviewRecord:
        self.get_answer(answer_id)
        review = ReviewRecord(id=str(uuid4()), answer_id=answer_id, result=result)
        self._store.write_yaml(
            f"assignment/reviews/{review.id}.yaml", review.model_dump(mode="json")
        )
        return review

    def latest_review(self, answer_id: str) -> ReviewRecord | None:
        matches = []
        for path in self._store.glob("assignment/reviews/*.yaml"):
            review = ReviewRecord.model_validate(
                self._store.read_yaml(path.relative_to(self._store.root))
            )
            if review.answer_id == answer_id:
                matches.append((path.stat().st_mtime_ns, review))
        return None if not matches else max(matches, key=lambda item: item[0])[1]

    def revise(
        self,
        source: AnswerRecord,
        review: ReviewRecord,
        content: str,
        member_id: str,
        mode: RevisionMode,
        summary: str,
        unresolved_issues: list[str] | None = None,
    ) -> tuple[AnswerRecord, RevisionRecord]:
        with self._lock:
            current = self.latest_answer()
            if current is None or current.id != source.id:
                raise ValueError("revision source must be the latest answer")
            if review.answer_id != source.id:
                raise ValueError("revision requires a review of its source answer")
            persisted_review = self.latest_review(source.id)
            if persisted_review is None or persisted_review.id != review.id:
                raise ValueError("revision review is not persisted for its source answer")
            if not summary.strip():
                raise ValueError("revision summary must not be blank")
            answer, answer_document = self._new_answer(content, member_id, source.version + 1)
            revision = RevisionRecord(
                id=str(uuid4()),
                source_answer_id=source.id,
                review_id=review.id,
                result_answer_id=answer.id,
                mode=mode,
                change_summary=summary,
                unresolved_issues=unresolved_issues or [],
            )
            self._store.write_batch(
                {
                    self._answer_path(answer.version): answer_document,
                    f"assignment/revisions/{answer.version:04d}.yaml": dump_yaml(
                        revision.model_dump(mode="json")
                    ),
                }
            )
            return answer, revision

    def latest_revision(self) -> RevisionRecord | None:
        paths = self._store.glob("assignment/revisions/*.yaml")
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

    def apply_agent_output(self, course_id: str, output: MainAgentResult, member_id: str) -> None:
        with self._lock:
            documents: dict[str, str] = {}
            latest = self.latest_answer()
            if output.notes_output is not None:
                note_id = str(uuid4())
                documents[f"courses/{course_id}/notes/{note_id}.yaml"] = dump_yaml(
                    output.notes_output.model_dump(mode="json")
                )
            if output.assignment_output is not None:
                version = 1 if latest is None else latest.version + 1
                latest, answer_document = self._new_answer(
                    output.assignment_output.shared_answer, member_id, version
                )
                documents[self._answer_path(version)] = answer_document
            review: ReviewRecord | None
            if output.review_output is not None:
                if latest is None:
                    raise ValueError("review requires a shared answer")
                review = ReviewRecord(
                    id=str(uuid4()), answer_id=latest.id, result=output.review_output
                )
                documents[f"assignment/reviews/{review.id}.yaml"] = dump_yaml(
                    review.model_dump(mode="json")
                )
            else:
                review = None if latest is None else self.latest_review(latest.id)
            if output.revision_output is not None:
                if latest is None or review is None:
                    raise ValueError("revision requires a review for the current answer")
                revised, revised_document = self._new_answer(
                    output.revision_output.revised_answer,
                    member_id,
                    latest.version + 1,
                )
                revision = RevisionRecord(
                    id=str(uuid4()),
                    source_answer_id=latest.id,
                    review_id=review.id,
                    result_answer_id=revised.id,
                    mode=output.revision_output.mode,
                    change_summary="；".join(output.revision_output.changes),
                    unresolved_issues=output.revision_output.unresolved_issues,
                )
                documents[self._answer_path(revised.version)] = revised_document
                documents[f"assignment/revisions/{revised.version:04d}.yaml"] = dump_yaml(
                    revision.model_dump(mode="json")
                )
            self._store.write_batch(documents)

    def _write_assignment(self, assignment: Assignment) -> None:
        self._store.write_text(
            "assignment/assignment.md",
            render_front_matter(
                {"id": assignment.id, "title": assignment.title, "rubric": assignment.rubric},
                assignment.requirements,
            ),
        )

    @staticmethod
    def _new_answer(content: str, member_id: str, version: int) -> tuple[AnswerRecord, str]:
        answer = AnswerRecord(
            id=str(uuid4()),
            version=version,
            content=content,
            operated_by_member_id=member_id,
        )
        document = render_front_matter(
            {
                "id": answer.id,
                "version": answer.version,
                "operated_by_member_id": member_id,
            },
            content,
        )
        return answer, document

    @staticmethod
    def _answer_path(version: int) -> str:
        return f"assignment/answers/{version:04d}.md"
