"""Application services for the single shared assignment lifecycle."""

from coursepilot.models import (
    AnswerComparison,
    AnswerRecord,
    Assignment,
    Course,
    CourseContext,
    MainAgentResult,
    NotesResult,
    ReviewRecord,
    ReviewResult,
    RevisionMode,
    RevisionRecord,
    Team,
    TeamMember,
)
from coursepilot.repositories import WorkspaceRepository


class WorkspaceService:
    def __init__(self, repository: WorkspaceRepository) -> None:
        self._repository = repository

    def initialize_team(self, name: str, members: list[TeamMember]) -> Team:
        return self._repository.initialize_team(name, members)

    def save_notes(self, course_id: str, result: NotesResult) -> str:
        return self._repository.save_notes(course_id, result)

    def get_team(self) -> Team:
        return self._repository.get_team()

    def initialize_assignment(
        self, title: str, requirements: str, rubric: str | None = None
    ) -> Assignment:
        return self._repository.initialize_assignment(title, requirements, rubric)

    def get_assignment(self) -> Assignment:
        return self._repository.get_assignment()

    def update_assignment(
        self, title: str, requirements: str, rubric: str | None = None
    ) -> Assignment:
        return self._repository.update_assignment(title, requirements, rubric)

    def save_answer(self, content: str, member_id: str) -> AnswerRecord:
        return self._repository.add_answer(content, member_id)

    def save_review(self, answer_id: str, result: ReviewResult) -> ReviewRecord:
        return self._repository.add_review(answer_id, result)

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
        return self._repository.revise(
            source, review, content, member_id, mode, summary, unresolved_issues
        )

    def context(self, course: Course) -> CourseContext:
        answer = self._repository.latest_answer()
        review = None if answer is None else self._repository.latest_review(answer.id)
        return CourseContext(
            active_course_id=course.id,
            active_course_name=course.name,
            current_answer=None if answer is None else answer.content,
            latest_review=None if review is None else review.result,
            answer_version=1 if answer is None else answer.version,
        )

    def compare_revision(self, revision: RevisionRecord) -> AnswerComparison:
        return self._repository.compare_revision(revision)

    def apply_agent_output(
        self, course: Course, output: MainAgentResult, member_id: str
    ) -> CourseContext:
        self._repository.apply_agent_output(course.id, output, member_id)
        return self.context(course)
