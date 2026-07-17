"""Framework-neutral UI state so the Streamlit shell stays thin and testable."""

from pydantic import BaseModel, ConfigDict

from coursepilot.models import (
    AnswerComparison,
    Assignment,
    Course,
    MaterialRecord,
    ReviewResult,
    Team,
)


class WorkspaceView(BaseModel):
    model_config = ConfigDict(frozen=True)

    team: Team
    courses: list[Course]
    assignments: list[Assignment]
    assignment: Assignment
    answer: str | None
    answer_version: int
    review: ReviewResult | None
    materials: list[MaterialRecord]
    comparison: AnswerComparison | None = None

    @property
    def active_course(self) -> Course | None:
        return next((course for course in self.courses if course.is_active), None)

    @property
    def can_create_assignment(self) -> bool:
        return True
