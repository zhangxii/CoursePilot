"""Pydantic contracts shared by the UI, agents, tools, and persistence layers."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NonEmptyText = Annotated[str, Field(min_length=1)]
PositiveVersion = Annotated[int, Field(ge=1)]


class Contract(BaseModel):
    """Strict base class for data crossing a module boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MaterialType(StrEnum):
    PDF = "pdf"
    PPTX = "pptx"
    NOTES = "notes"
    ASSIGNMENT = "assignment"
    FEEDBACK = "feedback"


class MaterialStatus(StrEnum):
    CURRENT = "current"
    ARCHIVED = "archived"


class RevisionMode(StrEnum):
    CONSERVATIVE = "conservative"
    DEEP_RESTRUCTURE = "deep_restructure"


class AgentKind(StrEnum):
    NOTES = "notes"
    ASSIGNMENT = "assignment"
    REVIEW = "review"
    REVISION = "revision"


class MaterialMetadata(Contract):
    course_id: NonEmptyText
    course_name: NonEmptyText
    course_date: date
    teacher: NonEmptyText
    topic: NonEmptyText
    material_type: MaterialType
    status: MaterialStatus


class TeamMember(Contract):
    id: NonEmptyText
    name: NonEmptyText
    role: str | None = None


class Team(Contract):
    id: Literal["main_team"] = "main_team"
    name: NonEmptyText
    members: Annotated[list[TeamMember], Field(min_length=1)]


class Assignment(Contract):
    id: Literal["main_assignment"] = "main_assignment"
    team_id: Literal["main_team"] = "main_team"
    title: NonEmptyText
    requirements: NonEmptyText
    rubric: str | None = None


class SourceRef(Contract):
    material_id: NonEmptyText
    file_name: NonEmptyText
    course_id: NonEmptyText
    page_or_section: NonEmptyText
    excerpt: NonEmptyText


class NotesResult(Contract):
    course_problem: NonEmptyText
    core_concepts: list[NonEmptyText]
    analysis_methods: list[NonEmptyText]
    examples: list[NonEmptyText]
    common_mistakes: list[NonEmptyText]
    teacher_criteria: list[NonEmptyText]
    practical_uses: list[NonEmptyText]
    prerequisite_relationships: list[NonEmptyText]
    sources: list[SourceRef]


class AssignmentResult(Contract):
    task_understanding: NonEmptyText
    shared_answer: NonEmptyText
    course_evidence: list[SourceRef]
    uncertainties: list[NonEmptyText]


class DimensionScore(Contract):
    dimension: NonEmptyText
    score: Annotated[int, Field(ge=0)]
    max_score: Annotated[int, Field(gt=0)]
    deduction: Annotated[int, Field(ge=0)]
    location: NonEmptyText
    evidence: Annotated[list[SourceRef], Field(min_length=1)]
    reason: NonEmptyText
    revision_advice: NonEmptyText

    @model_validator(mode="after")
    def validate_score_arithmetic(self) -> "DimensionScore":
        if self.score > self.max_score:
            raise ValueError("score must not exceed max_score")
        if self.deduction != self.max_score - self.score:
            raise ValueError("deduction must equal max_score minus score")
        return self


class ReviewResult(Contract):
    total_score: Annotated[int, Field(ge=0, le=100)]
    dimension_scores: Annotated[list[DimensionScore], Field(min_length=1)]
    strengths: list[NonEmptyText]
    critical_issues: list[NonEmptyText]
    likely_teacher_questions: list[NonEmptyText]
    revision_priorities: list[NonEmptyText]

    @model_validator(mode="after")
    def validate_total_score(self) -> "ReviewResult":
        if sum(item.score for item in self.dimension_scores) != self.total_score:
            raise ValueError("total_score must equal the sum of dimension scores")
        if sum(item.max_score for item in self.dimension_scores) != 100:
            raise ValueError("dimension max scores must sum to 100")
        return self


class CourseContext(Contract):
    active_course_id: NonEmptyText
    active_course_name: NonEmptyText
    team_id: Literal["main_team"] = "main_team"
    assignment_id: Literal["main_assignment"] = "main_assignment"
    current_answer: str | None = None
    latest_review: ReviewResult | None = None
    answer_version: PositiveVersion = 1


class RevisionResult(Contract):
    mode: RevisionMode
    source_version: PositiveVersion
    result_version: PositiveVersion
    revised_answer: NonEmptyText
    changes: Annotated[list[NonEmptyText], Field(min_length=1)]
    unresolved_issues: list[NonEmptyText]

    @model_validator(mode="after")
    def validate_version_progression(self) -> "RevisionResult":
        if self.result_version != self.source_version + 1:
            raise ValueError("result_version must be exactly one greater than source_version")
        return self


class MainAgentResult(Contract):
    intent: AgentKind
    invoked_agents: list[AgentKind]
    final_response: NonEmptyText
    context: CourseContext
