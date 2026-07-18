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
    MARKDOWN = "markdown"
    TEXT = "text"


class MaterialStatus(StrEnum):
    CURRENT = "current"
    ARCHIVED = "archived"


class IndexStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class Course(Contract):
    id: NonEmptyText
    name: NonEmptyText
    course_date: date
    teacher: NonEmptyText
    topic: NonEmptyText
    is_active: bool = False


class RevisionMode(StrEnum):
    CONSERVATIVE = "conservative"
    DEEP_RESTRUCTURE = "deep_restructure"


class AnswerSource(StrEnum):
    LEGACY = "legacy"
    USER_UPLOAD = "user_upload"
    ADOPTED_CANDIDATE = "adopted_candidate"


class AssignmentUploadPurpose(StrEnum):
    INITIAL_VERSION = "initial_version"
    NEW_FORMAL_VERSION = "new_formal_version"
    REFERENCE_ATTACHMENT = "reference_attachment"


class AttachmentPurpose(StrEnum):
    ASSIGNMENT_VERSION = "assignment_version"
    ASSIGNMENT_REFERENCE = "assignment_reference"
    OPTIMIZATION_DIRECTION = "optimization_direction"


class CandidateStatus(StrEnum):
    DRAFT = "draft"
    READY_FOR_ADOPTION = "ready_for_adoption"
    ADOPTED = "adopted"
    DISCARDED = "discarded"
    SUPERSEDED = "superseded"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class OptimizationTaskStatus(StrEnum):
    DRAFT = "draft"
    AWAITING_SELECTION = "awaiting_selection"
    READY_TO_GENERATE = "ready_to_generate"
    CANDIDATE_DRAFTED = "candidate_drafted"
    REVIEWED = "reviewed"
    READY_FOR_DECISION = "ready_for_decision"


class OptimizationDirectionSource(StrEnum):
    USER_TEXT = "user_text"
    USER_UPLOAD = "user_upload"
    AGENT_ANALYSIS = "agent_analysis"


class ReviewType(StrEnum):
    AUTOMATIC = "automatic"
    FORMAL = "formal"


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


class MaterialSearchAttributes(Contract):
    course_id: NonEmptyText
    course_name: NonEmptyText
    course_date: date
    teacher: NonEmptyText
    topic: NonEmptyText
    material_type: MaterialType
    status: MaterialStatus

    @classmethod
    def from_metadata(cls, metadata: MaterialMetadata) -> "MaterialSearchAttributes":
        return cls.model_validate(metadata.model_dump())


class MaterialRecord(Contract):
    id: NonEmptyText
    course_id: NonEmptyText
    file_name: NonEmptyText
    file_hash: NonEmptyText
    material_type: MaterialType
    status: MaterialStatus
    index_status: IndexStatus
    storage_path: str = ""
    error: str | None = None


class LocalMaterialDocument(Contract):
    material: MaterialRecord
    course_name: NonEmptyText
    course_date: date
    teacher: NonEmptyText
    topic: NonEmptyText


class TeamMember(Contract):
    id: NonEmptyText
    name: NonEmptyText
    role: str | None = None


class Team(Contract):
    id: Literal["main_team"] = "main_team"
    name: NonEmptyText
    members: Annotated[list[TeamMember], Field(min_length=1)]


class Assignment(Contract):
    id: NonEmptyText
    team_id: Literal["main_team"] = "main_team"
    title: NonEmptyText
    requirements: NonEmptyText
    rubric: str | None = None


class Conversation(Contract):
    id: NonEmptyText
    assignment_id: NonEmptyText
    team_id: Literal["main_team"] = "main_team"
    title: NonEmptyText
    base_answer_version_id: str | None = None
    parent_conversation_id: str | None = None
    forked_from_message_id: str | None = None
    status: ConversationStatus = ConversationStatus.ACTIVE

    @model_validator(mode="after")
    def validate_branch_links(self) -> "Conversation":
        if (self.parent_conversation_id is None) != (self.forked_from_message_id is None):
            raise ValueError("conversation branch requires both parent and message point")
        return self


class AnswerRecord(Contract):
    id: NonEmptyText
    assignment_id: NonEmptyText
    version: PositiveVersion
    content: NonEmptyText
    operated_by_member_id: NonEmptyText
    source: AnswerSource = AnswerSource.LEGACY
    based_on_version_id: str | None = None
    source_attachment_id: str | None = None
    adopted_candidate_id: str | None = None
    automatic_review_id: NonEmptyText | None = None
    revision_mode: RevisionMode | None = None
    version_note: str | None = None


class AttachmentRecord(Contract):
    id: NonEmptyText
    assignment_id: NonEmptyText
    purpose: AttachmentPurpose
    original_file_name: NonEmptyText
    original_path: NonEmptyText
    normalized_path: NonEmptyText
    normalized_content: NonEmptyText
    content_hash: NonEmptyText


class ImportedAssignment(Contract):
    attachment: AttachmentRecord
    answer_version: AnswerRecord | None = None


class CandidateDraft(Contract):
    id: NonEmptyText
    assignment_id: NonEmptyText
    conversation_id: NonEmptyText
    base_answer_version_id: str | None = None
    derived_from_candidate_id: str | None = None
    superseded_by_candidate_id: str | None = None
    content: NonEmptyText
    status: CandidateStatus = CandidateStatus.DRAFT
    automatic_review_id: NonEmptyText | None = None
    revision_mode: RevisionMode | None = None
    change_summary: str = ""
    resolved_issues: list[NonEmptyText] = Field(default_factory=list)
    unresolved_issues: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state_links(self) -> "CandidateDraft":
        reviewed = self.automatic_review_id is not None
        if self.status in {CandidateStatus.READY_FOR_ADOPTION, CandidateStatus.ADOPTED}:
            if not reviewed:
                raise ValueError("ready or adopted candidate requires an automatic review")
        elif reviewed:
            raise ValueError("only ready or adopted candidate may reference an automatic review")
        if self.status is CandidateStatus.SUPERSEDED:
            if self.superseded_by_candidate_id is None:
                raise ValueError("superseded candidate requires its replacement")
        elif self.superseded_by_candidate_id is not None:
            raise ValueError("only superseded candidate may reference its replacement")
        return self


class AutomaticReviewRecord(Contract):
    id: NonEmptyText
    candidate_id: NonEmptyText
    review_type: Literal[ReviewType.AUTOMATIC] = ReviewType.AUTOMATIC
    triggered_by: Literal["system"] = "system"
    result: "ReviewResult"


class CandidateComparison(Contract):
    candidate_id: NonEmptyText
    base_answer_version_id: str | None = None
    base_content: str
    candidate_content: NonEmptyText
    unified_diff: NonEmptyText
    change_summary: str = ""
    resolved_issues: list[NonEmptyText] = Field(default_factory=list)
    unresolved_issues: list[NonEmptyText] = Field(default_factory=list)


class OptimizationIssue(Contract):
    id: NonEmptyText
    problem: NonEmptyText
    reason: NonEmptyText
    impact: NonEmptyText
    priority: Annotated[int, Field(ge=1)]


class OptimizationAnalysisInput(Contract):
    assignment_id: NonEmptyText
    assignment_requirements: NonEmptyText
    rubric: str | None = None
    base_content: NonEmptyText
    course_evidence: list["SourceRef"] = Field(default_factory=list)


class OptimizationAnalysisResult(Contract):
    issues: Annotated[list[OptimizationIssue], Field(min_length=1)]


class OptimizationDirectionAttachment(Contract):
    id: NonEmptyText
    task_id: NonEmptyText
    original_file_name: NonEmptyText
    original_path: NonEmptyText
    normalized_path: NonEmptyText
    normalized_content: NonEmptyText


class OptimizationTask(Contract):
    id: NonEmptyText
    assignment_id: NonEmptyText
    conversation_id: NonEmptyText
    base_answer_version_id: str | None = None
    base_candidate_draft_id: str | None = None
    mode: RevisionMode
    user_direction: str | None = None
    direction_attachment_id: str | None = None
    direction_text: str | None = None
    direction_source: OptimizationDirectionSource | None = None
    agent_suggestions: list[OptimizationIssue] = Field(default_factory=list)
    selected_agent_suggestions: list[NonEmptyText] = Field(default_factory=list)
    preserve_constraints: list[NonEmptyText] = Field(default_factory=list)
    prohibited_changes: list[NonEmptyText] = Field(default_factory=list)
    format_constraints: list[NonEmptyText] = Field(default_factory=list)
    max_words: Annotated[int, Field(ge=1)] | None = None
    max_characters: Annotated[int, Field(ge=1)] | None = None
    status: OptimizationTaskStatus = OptimizationTaskStatus.DRAFT
    result_candidate_id: str | None = None
    first_review_id: str | None = None
    final_review_id: str | None = None
    correction_count: Annotated[int, Field(ge=0, le=1)] = 0
    fixed_issues: list[NonEmptyText] = Field(default_factory=list)
    pending_issues: list[NonEmptyText] = Field(default_factory=list)
    auto_fixable_issues: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_base(self) -> "OptimizationTask":
        if (self.base_answer_version_id is None) == (self.base_candidate_draft_id is None):
            raise ValueError("optimization task requires exactly one base")
        has_direction = self.direction_text is not None and self.direction_source is not None
        if (self.direction_text is None) != (self.direction_source is None):
            raise ValueError("direction text and source must be set together")
        if self.status is OptimizationTaskStatus.AWAITING_SELECTION and (
            not self.agent_suggestions or self.selected_agent_suggestions
        ):
            raise ValueError("awaiting selection requires unselected Agent suggestions")
        if (
            self.status is OptimizationTaskStatus.READY_TO_GENERATE
            and not has_direction
            and not self.selected_agent_suggestions
        ):
            raise ValueError("ready task requires a confirmed direction")
        if (
            self.status
            in {
                OptimizationTaskStatus.CANDIDATE_DRAFTED,
                OptimizationTaskStatus.REVIEWED,
                OptimizationTaskStatus.READY_FOR_DECISION,
            }
            and self.result_candidate_id is None
        ):
            raise ValueError("advanced optimization state requires a result candidate")
        if self.status is OptimizationTaskStatus.REVIEWED and (
            self.first_review_id is None or not self.auto_fixable_issues
        ):
            raise ValueError("reviewed task requires a review and fixable issues")
        if (
            self.status is OptimizationTaskStatus.READY_FOR_DECISION
            and self.final_review_id is None
        ):
            raise ValueError("decision-ready task requires a final review")
        pre_candidate = {
            OptimizationTaskStatus.DRAFT,
            OptimizationTaskStatus.AWAITING_SELECTION,
            OptimizationTaskStatus.READY_TO_GENERATE,
        }
        if self.status in pre_candidate and any(
            value is not None
            for value in (self.result_candidate_id, self.first_review_id, self.final_review_id)
        ):
            raise ValueError("pre-generation task cannot reference candidate or review results")
        if self.status is OptimizationTaskStatus.CANDIDATE_DRAFTED and any(
            value is not None for value in (self.first_review_id, self.final_review_id)
        ):
            raise ValueError("drafted candidate cannot already reference reviews")
        if self.status is OptimizationTaskStatus.REVIEWED and self.final_review_id is not None:
            raise ValueError("task awaiting correction cannot have a final review")
        if (
            self.correction_count == 1
            and self.status is not OptimizationTaskStatus.READY_FOR_DECISION
        ):
            raise ValueError("bounded correction must end in user decision state")
        return self


class AutomaticReviewInput(Contract):
    assignment_id: NonEmptyText
    assignment_requirements: NonEmptyText
    rubric: str | None = None
    candidate_id: NonEmptyText
    candidate_content: NonEmptyText
    course_evidence: list["SourceRef"] = Field(default_factory=list)
    mode: RevisionMode | None = None
    preserve_constraints: list[NonEmptyText] = Field(default_factory=list)
    prohibited_changes: list[NonEmptyText] = Field(default_factory=list)
    format_constraints: list[NonEmptyText] = Field(default_factory=list)
    max_words: Annotated[int, Field(ge=1)] | None = None
    max_characters: Annotated[int, Field(ge=1)] | None = None


class OptimizationCorrectionInput(Contract):
    candidate_content: NonEmptyText
    issues: list[NonEmptyText]
    mode: RevisionMode
    preserve_constraints: list[NonEmptyText] = Field(default_factory=list)
    prohibited_changes: list[NonEmptyText] = Field(default_factory=list)
    format_constraints: list[NonEmptyText] = Field(default_factory=list)
    max_words: Annotated[int, Field(ge=1)] | None = None
    max_characters: Annotated[int, Field(ge=1)] | None = None


class AnswerVersionComparison(Contract):
    source_answer_id: NonEmptyText
    result_answer_id: NonEmptyText
    source_version: PositiveVersion
    result_version: PositiveVersion
    source_content: NonEmptyText
    result_content: NonEmptyText
    unified_diff: NonEmptyText
    change_summary: str = ""
    resolved_issues: list[NonEmptyText] = Field(default_factory=list)
    unresolved_issues: list[NonEmptyText] = Field(default_factory=list)


class ReviewRecord(Contract):
    id: NonEmptyText
    answer_id: NonEmptyText
    review_type: Literal[ReviewType.FORMAL] = ReviewType.FORMAL
    triggered_by: NonEmptyText = "user"
    result: "ReviewResult"


class RevisionRecord(Contract):
    id: NonEmptyText
    source_answer_id: NonEmptyText
    review_id: NonEmptyText
    result_answer_id: NonEmptyText
    mode: RevisionMode
    change_summary: NonEmptyText
    unresolved_issues: list[NonEmptyText] = []


class AnswerComparison(Contract):
    source_version: PositiveVersion
    result_version: PositiveVersion
    operated_by_member_id: NonEmptyText
    change_summary: NonEmptyText
    resolved_issues: list[NonEmptyText]
    unresolved_issues: list[NonEmptyText]


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


class ConversationContext(Contract):
    conversation_id: NonEmptyText = "legacy-conversation"
    active_course_id: NonEmptyText
    active_course_name: NonEmptyText
    team_id: Literal["main_team"] = "main_team"
    active_assignment_id: NonEmptyText
    base_answer_version_id: str | None = None
    current_answer: str | None = None
    latest_review: ReviewResult | None = None
    answer_version: PositiveVersion = 1


CourseContext = ConversationContext


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
    context: ConversationContext
    notes_output: NotesResult | None = None
    assignment_output: AssignmentResult | None = None
    review_output: ReviewResult | None = None
    revision_output: RevisionResult | None = None
