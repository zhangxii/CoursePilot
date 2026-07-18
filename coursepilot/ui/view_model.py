"""Framework-neutral UI state so the Streamlit shell stays thin and testable."""

from pydantic import BaseModel, ConfigDict, Field

from coursepilot.models import (
    AnswerComparison,
    AnswerRecord,
    Assignment,
    AttachmentRecord,
    CandidateDraft,
    Conversation,
    Course,
    MaterialRecord,
    OptimizationTask,
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
    formal_answer: AnswerRecord | None = None
    answer_versions: list[AnswerRecord] = Field(default_factory=list)
    attachments: list[AttachmentRecord] = Field(default_factory=list)
    conversations: list[Conversation] = Field(default_factory=list)
    active_conversation: Conversation | None = None
    candidates: list[CandidateDraft] = Field(default_factory=list)
    candidate_reviews: dict[str, ReviewResult] = Field(default_factory=dict)
    formal_reviews: dict[str, ReviewResult] = Field(default_factory=dict)
    optimization_tasks: list[OptimizationTask] = Field(default_factory=list)

    @property
    def active_course(self) -> Course | None:
        return next((course for course in self.courses if course.is_active), None)

    @property
    def can_create_assignment(self) -> bool:
        return True

    @property
    def pending_issue_count(self) -> int:
        candidate_issues = sum(len(item.unresolved_issues) for item in self.candidates)
        optimization_issues = sum(len(item.pending_issues) for item in self.optimization_tasks)
        return candidate_issues + optimization_issues
