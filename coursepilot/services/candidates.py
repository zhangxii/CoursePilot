"""Candidate draft lifecycle and the explicit formal-version adoption seam."""

from difflib import unified_diff
from pathlib import Path

from coursepilot.models import (
    AnswerRecord,
    CandidateComparison,
    CandidateDraft,
    ReviewResult,
    RevisionMode,
)
from coursepilot.repositories import WorkspaceRepository
from coursepilot.services.workspace import WorkspaceService


class CandidateDraftService:
    def __init__(self, data_root: str | Path, workspace: WorkspaceService) -> None:
        self._repository = WorkspaceRepository(data_root)
        self._workspace = workspace

    def create(
        self,
        content: str,
        conversation_id: str,
        *,
        change_summary: str = "",
        resolved_issues: list[str] | None = None,
        unresolved_issues: list[str] | None = None,
        revision_mode: RevisionMode | None = None,
        base_answer_version_id: str | None = None,
        derived_from_candidate_id: str | None = None,
    ) -> CandidateDraft:
        assignment = self._workspace.get_assignment()
        return self._repository.create_candidate(
            content,
            conversation_id,
            assignment.id,
            change_summary=change_summary,
            resolved_issues=resolved_issues,
            unresolved_issues=unresolved_issues,
            revision_mode=revision_mode,
            base_answer_version_id=base_answer_version_id,
            derived_from_candidate_id=derived_from_candidate_id,
        )

    def get(self, candidate_id: str) -> CandidateDraft:
        return self._repository.get_candidate(candidate_id)

    def complete_automatic_review(self, candidate_id: str, result: ReviewResult) -> CandidateDraft:
        return self._repository.complete_candidate_review(candidate_id, result)

    def complete_review_cycle(
        self,
        candidate_id: str,
        first_review: ReviewResult,
        *,
        corrected_content: str | None = None,
        final_review: ReviewResult | None = None,
    ) -> CandidateDraft:
        return self._repository.complete_candidate_review_cycle(
            candidate_id,
            first_review,
            corrected_content=corrected_content,
            final_review=final_review,
        )

    def discard(self, candidate_id: str) -> CandidateDraft:
        candidate = self.get(candidate_id)
        if candidate.assignment_id != self._workspace.get_assignment().id:
            raise ValueError("candidate does not belong to the active assignment")
        return self._repository.discard_candidate(candidate_id)

    def continue_from(self, candidate_id: str, content: str) -> CandidateDraft:
        candidate = self.get(candidate_id)
        if candidate.assignment_id != self._workspace.get_assignment().id:
            raise ValueError("candidate does not belong to the active assignment")
        return self._repository.continue_candidate(candidate_id, content)

    def compare_to_base(self, candidate_id: str) -> CandidateComparison:
        candidate = self.get(candidate_id)
        base = (
            None
            if candidate.base_answer_version_id is None
            else self._workspace.get_answer(candidate.base_answer_version_id)
        )
        base_content = "" if base is None else base.content
        diff = "\n".join(
            unified_diff(
                base_content.splitlines(),
                candidate.content.splitlines(),
                fromfile="formal-version",
                tofile="candidate",
                lineterm="",
            )
        )
        return CandidateComparison(
            candidate_id=candidate.id,
            base_answer_version_id=candidate.base_answer_version_id,
            base_content=base_content,
            candidate_content=candidate.content,
            unified_diff=diff or "No textual changes",
            change_summary=candidate.change_summary,
            resolved_issues=candidate.resolved_issues,
            unresolved_issues=candidate.unresolved_issues,
        )

    def _adopt(self, candidate_id: str, member_id: str) -> AnswerRecord:
        return self._repository.adopt_candidate(candidate_id, member_id)


class AdoptCandidateService:
    """The only application interface allowed to publish an Agent candidate."""

    def __init__(self, candidates: CandidateDraftService, workspace: WorkspaceService) -> None:
        self._candidates = candidates
        self._workspace = workspace

    def adopt(self, candidate_id: str, member_id: str) -> AnswerRecord:
        candidate = self._candidates.get(candidate_id)
        if candidate.assignment_id != self._workspace.get_assignment().id:
            raise ValueError("candidate does not belong to the active assignment")
        return self._candidates._adopt(candidate_id, member_id)
