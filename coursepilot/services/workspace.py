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

    def create_assignment(
        self,
        assignment_id: str,
        title: str,
        requirements: str,
        rubric: str | None = None,
    ) -> Assignment:
        return self._repository.create_assignment(assignment_id, title, requirements, rubric)

    def list_assignments(self) -> list[Assignment]:
        return self._repository.list_assignments()

    def get_assignment(self, assignment_id: str | None = None) -> Assignment:
        return self._repository.get_assignment(assignment_id)

    def activate_assignment(self, assignment_id: str) -> Assignment:
        return self._repository.activate_assignment(assignment_id)

    def update_assignment(
        self,
        assignment_id: str,
        title: str,
        requirements: str,
        rubric: str | None = None,
    ) -> Assignment:
        return self._repository.update_assignment(assignment_id, title, requirements, rubric)

    def get_answer(self, answer_id: str) -> AnswerRecord:
        return self._repository.get_answer(answer_id)

    def latest_answer(self) -> AnswerRecord | None:
        return self._repository.latest_answer()

    def list_answers(self) -> list[AnswerRecord]:
        return self._repository.list_answers()

    def save_review(self, answer_id: str, result: ReviewResult) -> ReviewRecord:
        return self._repository.add_review(answer_id, result)

    def context(self, course: Course) -> CourseContext:
        assignment = self.get_assignment()
        answer = self._repository.latest_answer()
        review = None if answer is None else self._repository.latest_review(answer.id)
        return CourseContext(
            active_course_id=course.id,
            active_course_name=course.name,
            active_assignment_id=assignment.id,
            current_answer=None if answer is None else answer.content,
            latest_review=None if review is None else review.result,
            answer_version=1 if answer is None else answer.version,
        )

    def compare_revision(self, revision: RevisionRecord) -> AnswerComparison:
        return self._repository.compare_revision(revision)

    def apply_agent_output(
        self, course: Course, output: MainAgentResult, member_id: str
    ) -> CourseContext:
        active_assignment_id = self.get_assignment().id
        if output.context.active_assignment_id != active_assignment_id:
            raise ValueError("agent output assignment does not match the active assignment")
        self._repository.apply_agent_output(course.id, output, member_id)
        return self.context(course)
