"""Directed optimization tasks and the bounded automatic-review workflow."""

import re
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from coursepilot.file_store import FileDataStore, dump_yaml
from coursepilot.models import (
    AutomaticReviewInput,
    AutomaticReviewRecord,
    CandidateDraft,
    CandidateStatus,
    OptimizationAnalysisInput,
    OptimizationCorrectionInput,
    OptimizationDirectionAttachment,
    OptimizationDirectionSource,
    OptimizationIssue,
    OptimizationTask,
    OptimizationTaskStatus,
    ReviewResult,
    RevisionMode,
    SourceRef,
)
from coursepilot.repositories import ConversationRepository, WorkspaceRepository
from coursepilot.services.artifacts import AssignmentArtifactService
from coursepilot.services.candidates import CandidateDraftService
from coursepilot.services.workspace import WorkspaceService


class AutomaticReviewer(Protocol):
    def review(self, request: AutomaticReviewInput) -> ReviewResult: ...


class AutomaticCorrector(Protocol):
    def correct(self, request: OptimizationCorrectionInput) -> str: ...


class ProblemAnalyzer(Protocol):
    def analyze(self, request: OptimizationAnalysisInput) -> list[OptimizationIssue]: ...


class OptimizationService:
    def __init__(self, data_root: str | Path, workspace: WorkspaceService) -> None:
        root = Path(data_root)
        self._store = FileDataStore(root)
        self._workspace = workspace
        self.candidates = CandidateDraftService(data_root, workspace)
        self._conversations = ConversationRepository(root)

    def create_for_answer(
        self,
        conversation_id: str,
        answer_version_id: str,
        mode: RevisionMode,
        *,
        user_direction: str | None = None,
        preserve_constraints: list[str] | None = None,
        prohibited_changes: list[str] | None = None,
        format_constraints: list[str] | None = None,
        max_words: int | None = None,
        max_characters: int | None = None,
    ) -> OptimizationTask:
        answer = self._workspace.get_answer(answer_version_id)
        assignment = self._workspace.get_assignment()
        if answer.assignment_id != assignment.id:
            raise ValueError("base answer does not belong to the active assignment")
        conversation = self._conversations.get(assignment.id, conversation_id)
        if conversation.base_answer_version_id != answer.id:
            raise ValueError("base answer does not match the selected conversation")
        direction = None if user_direction is None else user_direction.strip()
        task = OptimizationTask(
            id=str(uuid4()),
            assignment_id=answer.assignment_id,
            conversation_id=conversation_id,
            base_answer_version_id=answer.id,
            mode=mode,
            user_direction=direction or None,
            direction_text=direction or None,
            direction_source=(OptimizationDirectionSource.USER_TEXT if direction else None),
            preserve_constraints=preserve_constraints or [],
            prohibited_changes=prohibited_changes or [],
            format_constraints=format_constraints or [],
            max_words=max_words,
            max_characters=max_characters,
            status=(
                OptimizationTaskStatus.READY_TO_GENERATE
                if direction
                else OptimizationTaskStatus.DRAFT
            ),
        )
        self._write(task)
        return task

    def create_for_candidate(
        self,
        conversation_id: str,
        candidate_id: str,
        mode: RevisionMode,
        *,
        user_direction: str | None = None,
        preserve_constraints: list[str] | None = None,
        prohibited_changes: list[str] | None = None,
        format_constraints: list[str] | None = None,
        max_words: int | None = None,
        max_characters: int | None = None,
    ) -> OptimizationTask:
        candidate = self.candidates.get(candidate_id)
        assignment = self._workspace.get_assignment()
        if candidate.assignment_id != assignment.id:
            raise ValueError("base candidate does not belong to the active assignment")
        conversation = self._conversations.get(assignment.id, conversation_id)
        if candidate.conversation_id != conversation_id:
            raise ValueError("base candidate does not belong to the selected conversation")
        if candidate.base_answer_version_id != conversation.base_answer_version_id:
            raise ValueError("base candidate version does not match the selected conversation")
        direction = None if user_direction is None else user_direction.strip()
        task = OptimizationTask(
            id=str(uuid4()),
            assignment_id=candidate.assignment_id,
            conversation_id=conversation_id,
            base_candidate_draft_id=candidate.id,
            mode=mode,
            user_direction=direction or None,
            direction_text=direction or None,
            direction_source=(OptimizationDirectionSource.USER_TEXT if direction else None),
            preserve_constraints=preserve_constraints or [],
            prohibited_changes=prohibited_changes or [],
            format_constraints=format_constraints or [],
            max_words=max_words,
            max_characters=max_characters,
            status=(
                OptimizationTaskStatus.READY_TO_GENERATE
                if direction
                else OptimizationTaskStatus.DRAFT
            ),
        )
        self._write(task)
        return task

    def get(self, task_id: str) -> OptimizationTask:
        assignment_id = self._workspace.get_assignment().id
        path = f"assignments/{assignment_id}/optimization-tasks/{task_id}.yaml"
        if not self._store.exists(path):
            raise KeyError(task_id)
        return OptimizationTask.model_validate(self._store.read_yaml(path))

    def base_content(self, task_id: str) -> str:
        task = self.get(task_id)
        if task.base_answer_version_id is not None:
            return self._workspace.get_answer(task.base_answer_version_id).content
        if task.base_candidate_draft_id is None:
            raise ValueError("optimization task has no base")
        return self.candidates.get(task.base_candidate_draft_id).content

    def attach_direction(self, task_id: str, file_name: str, content: bytes) -> OptimizationTask:
        task = self.get(task_id)
        if len(content) > 20 * 1024 * 1024:
            raise ValueError("optimization direction exceeds 20971520 bytes")
        normalized = AssignmentArtifactService._decode_text(file_name, content)
        safe_name = AssignmentArtifactService._safe_name(file_name)
        attachment = OptimizationDirectionAttachment(
            id=str(uuid4()),
            task_id=task.id,
            original_file_name=file_name,
            original_path=f"assignments/{task.assignment_id}/optimization-directions/{task.id}/{safe_name}",
            normalized_path=(
                f"assignments/{task.assignment_id}/optimization-directions/{task.id}/direction.md"
            ),
            normalized_content=normalized,
        )
        updated = self._updated(
            task,
            direction_attachment_id=attachment.id,
            direction_text=normalized,
            direction_source=OptimizationDirectionSource.USER_UPLOAD,
            status=OptimizationTaskStatus.READY_TO_GENERATE,
        )
        metadata = attachment.model_dump(mode="json", exclude={"normalized_content"})
        self._store.write_batch(
            {
                attachment.original_path: content,
                attachment.normalized_path: normalized,
                self._direction_metadata_path(task): dump_yaml(metadata),
                self._path(updated): dump_yaml(updated.model_dump(mode="json")),
            }
        )
        return updated

    def record_analysis(
        self, task_id: str, suggestions: list[OptimizationIssue]
    ) -> OptimizationTask:
        if not suggestions:
            raise ValueError("problem analysis must contain at least one suggestion")
        task = self.get(task_id)
        updated = self._updated(
            task,
            agent_suggestions=suggestions,
            status=OptimizationTaskStatus.AWAITING_SELECTION,
        )
        self._write(updated)
        return updated

    def analyze_problems(
        self,
        task_id: str,
        analyzer: ProblemAnalyzer,
        *,
        course_evidence: list[SourceRef] | None = None,
    ) -> OptimizationTask:
        task = self.get(task_id)
        if task.direction_text is not None:
            raise ValueError("problem analysis is only for tasks without user direction")
        base_content = self.base_content(task.id)
        assignment = self._workspace.get_assignment()
        suggestions = analyzer.analyze(
            OptimizationAnalysisInput(
                assignment_id=assignment.id,
                assignment_requirements=assignment.requirements,
                rubric=assignment.rubric,
                base_content=base_content,
                course_evidence=course_evidence or [],
            )
        )
        return self.record_analysis(task.id, suggestions)

    def confirm_suggestions(
        self,
        task_id: str,
        suggestion_ids: list[str],
        *,
        supplemental_direction: str | None = None,
    ) -> OptimizationTask:
        task = self.get(task_id)
        known = {item.id for item in task.agent_suggestions}
        if not suggestion_ids or not set(suggestion_ids).issubset(known):
            raise ValueError("selected suggestions must come from the analysis")
        selected = [item.problem for item in task.agent_suggestions if item.id in suggestion_ids]
        supplement = None if supplemental_direction is None else supplemental_direction.strip()
        if supplement:
            selected.append(supplement)
        updated = self._updated(
            task,
            selected_agent_suggestions=suggestion_ids,
            direction_text="；".join(selected),
            direction_source=OptimizationDirectionSource.AGENT_ANALYSIS,
            status=OptimizationTaskStatus.READY_TO_GENERATE,
        )
        self._write(updated)
        return updated

    def create_candidate(self, task_id: str, content: str) -> CandidateDraft:
        task = self.get(task_id)
        if task.status is not OptimizationTaskStatus.READY_TO_GENERATE:
            raise ValueError("optimization task requires confirmed direction")
        self._validate_constraints(task, content)
        base_candidate = (
            None
            if task.base_candidate_draft_id is None
            else self.candidates.get(task.base_candidate_draft_id)
        )
        candidate = CandidateDraft(
            id=str(uuid4()),
            assignment_id=task.assignment_id,
            conversation_id=task.conversation_id,
            content=content,
            revision_mode=task.mode,
            base_answer_version_id=(
                task.base_answer_version_id
                if base_candidate is None
                else base_candidate.base_answer_version_id
            ),
            derived_from_candidate_id=task.base_candidate_draft_id,
        )
        updated = self._updated(
            task,
            result_candidate_id=candidate.id,
            status=OptimizationTaskStatus.CANDIDATE_DRAFTED,
        )
        self._store.write_batch(
            {
                WorkspaceRepository.candidate_storage_path(
                    candidate.assignment_id, candidate.id
                ): WorkspaceRepository.candidate_document(candidate),
                self._path(updated): dump_yaml(updated.model_dump(mode="json")),
            }
        )
        return candidate

    def record_automatic_review(
        self,
        task_id: str,
        candidate_id: str,
        result: ReviewResult,
        *,
        auto_fixable_issues: list[str] | None = None,
    ) -> OptimizationTask:
        task = self.get(task_id)
        if task.status is not OptimizationTaskStatus.CANDIDATE_DRAFTED:
            raise ValueError("only a newly drafted candidate can receive its first review")
        if task.result_candidate_id != candidate_id:
            raise ValueError("review candidate does not belong to optimization task")
        candidate = self._candidate_for_task(task, candidate_id)
        if candidate.status is not CandidateStatus.DRAFT:
            raise ValueError("only a draft candidate can be reviewed")
        fixable = auto_fixable_issues or []
        if not set(fixable).issubset(result.critical_issues):
            raise ValueError("auto-fixable issues must come from the review")
        review = AutomaticReviewRecord(id=str(uuid4()), candidate_id=candidate.id, result=result)
        ready = (
            candidate
            if fixable
            else CandidateDraft.model_validate(
                {
                    **candidate.model_dump(mode="json"),
                    "status": CandidateStatus.READY_FOR_ADOPTION,
                    "automatic_review_id": review.id,
                }
            )
        )
        updated = self._updated(
            task,
            first_review_id=review.id,
            final_review_id=None if fixable else review.id,
            pending_issues=result.critical_issues,
            auto_fixable_issues=fixable,
            status=(
                OptimizationTaskStatus.REVIEWED
                if fixable
                else OptimizationTaskStatus.READY_FOR_DECISION
            ),
        )
        documents = {
            WorkspaceRepository.candidate_review_storage_path(
                candidate.assignment_id, review.id
            ): dump_yaml(review.model_dump(mode="json")),
            self._path(updated): dump_yaml(updated.model_dump(mode="json")),
        }
        if not fixable:
            documents[
                WorkspaceRepository.candidate_storage_path(candidate.assignment_id, candidate.id)
            ] = WorkspaceRepository.candidate_document(ready)
        self._store.write_batch(documents)
        return updated

    def run_automatic_review(
        self,
        task_id: str,
        reviewer: AutomaticReviewer,
        *,
        corrector: AutomaticCorrector | None = None,
        course_evidence: list[SourceRef] | None = None,
    ) -> OptimizationTask:
        task = self.get(task_id)
        if task.result_candidate_id is None:
            raise ValueError("optimization task has no candidate")
        candidate = self._candidate_for_task(task, task.result_candidate_id)
        assignment = self._workspace.get_assignment()
        request = AutomaticReviewInput(
            assignment_id=assignment.id,
            assignment_requirements=assignment.requirements,
            rubric=assignment.rubric,
            candidate_id=candidate.id,
            candidate_content=candidate.content,
            course_evidence=course_evidence or [],
            mode=task.mode,
            preserve_constraints=task.preserve_constraints,
            prohibited_changes=task.prohibited_changes,
            format_constraints=task.format_constraints,
            max_words=task.max_words,
            max_characters=task.max_characters,
        )
        first = reviewer.review(request)
        fixable = first.critical_issues if corrector is not None else []
        reviewed = self.record_automatic_review(
            task.id, candidate.id, first, auto_fixable_issues=fixable
        )
        if not fixable or corrector is None:
            return reviewed
        corrected = corrector.correct(
            OptimizationCorrectionInput(
                candidate_content=candidate.content,
                issues=fixable,
                mode=task.mode,
                preserve_constraints=task.preserve_constraints,
                prohibited_changes=task.prohibited_changes,
                format_constraints=task.format_constraints,
                max_words=task.max_words,
                max_characters=task.max_characters,
            )
        )
        self._validate_constraints(task, corrected)
        second_candidate = self._new_corrected_candidate(candidate, corrected, task.mode)
        second_request = request.model_copy(
            update={
                "candidate_id": second_candidate.id,
                "candidate_content": second_candidate.content,
            }
        )
        second = reviewer.review(second_request)
        return self._commit_correction(reviewed, candidate, second_candidate, second, fixable)

    def apply_bounded_correction(
        self,
        task_id: str,
        corrected_content: str,
        re_review: ReviewResult,
        *,
        fixed_issues: list[str] | None = None,
    ) -> OptimizationTask:
        task = self.get(task_id)
        if task.correction_count >= 1:
            raise ValueError("automatic workflow permits at most one correction")
        if task.status is not OptimizationTaskStatus.REVIEWED or task.result_candidate_id is None:
            raise ValueError("candidate must have a review before correction")
        self._validate_constraints(task, corrected_content)
        source = self._candidate_for_task(task, task.result_candidate_id)
        child = self._new_corrected_candidate(source, corrected_content, task.mode)
        return self._commit_correction(task, source, child, re_review, fixed_issues or [])

    def _commit_correction(
        self,
        task: OptimizationTask,
        source: CandidateDraft,
        child: CandidateDraft,
        re_review: ReviewResult,
        attempted_fixes: list[str],
    ) -> OptimizationTask:
        if source.status is not CandidateStatus.DRAFT:
            raise ValueError("only a draft candidate can be corrected")
        review = AutomaticReviewRecord(id=str(uuid4()), candidate_id=child.id, result=re_review)
        ready = CandidateDraft.model_validate(
            {
                **child.model_dump(mode="json"),
                "status": CandidateStatus.READY_FOR_ADOPTION,
                "automatic_review_id": review.id,
            }
        )
        superseded = CandidateDraft.model_validate(
            {
                **source.model_dump(mode="json"),
                "status": CandidateStatus.SUPERSEDED,
                "superseded_by_candidate_id": ready.id,
            }
        )
        fixed = [item for item in attempted_fixes if item not in re_review.critical_issues]
        updated = self._updated(
            task,
            result_candidate_id=ready.id,
            final_review_id=review.id,
            correction_count=1,
            fixed_issues=fixed,
            pending_issues=re_review.critical_issues,
            status=OptimizationTaskStatus.READY_FOR_DECISION,
        )
        self._store.write_batch(
            {
                WorkspaceRepository.candidate_storage_path(
                    source.assignment_id, source.id
                ): WorkspaceRepository.candidate_document(superseded),
                WorkspaceRepository.candidate_storage_path(
                    ready.assignment_id, ready.id
                ): WorkspaceRepository.candidate_document(ready),
                WorkspaceRepository.candidate_review_storage_path(
                    ready.assignment_id, review.id
                ): dump_yaml(review.model_dump(mode="json")),
                self._path(updated): dump_yaml(updated.model_dump(mode="json")),
            }
        )
        return updated

    @staticmethod
    def _new_corrected_candidate(
        source: CandidateDraft, content: str, mode: RevisionMode
    ) -> CandidateDraft:
        return CandidateDraft(
            id=str(uuid4()),
            assignment_id=source.assignment_id,
            conversation_id=source.conversation_id,
            base_answer_version_id=source.base_answer_version_id,
            derived_from_candidate_id=source.id,
            content=content,
            revision_mode=mode,
        )

    def _validate_constraints(self, task: OptimizationTask, content: str) -> None:
        if task.mode is RevisionMode.CONSERVATIVE:
            missing = [item for item in task.preserve_constraints if item not in content]
            if missing:
                raise ValueError(f"conservative revision removed preserved content: {missing}")
        forbidden = [item for item in task.prohibited_changes if item in content]
        if forbidden:
            raise ValueError(f"revision contains prohibited content: {forbidden}")
        if task.max_words is not None and len(content.split()) > task.max_words:
            raise ValueError("revision exceeds the requested word limit")
        character_count = len(re.sub(r"\s+", "", content))
        if task.max_characters is not None and character_count > task.max_characters:
            raise ValueError("revision exceeds the requested character limit")
        for constraint in task.format_constraints:
            normalized = constraint.lower()
            if ("table" in normalized or "表格" in normalized) and "|" not in content:
                raise ValueError("revision must contain a Markdown table")
            if ("heading" in normalized or "标题" in normalized) and not any(
                line.lstrip().startswith("#") for line in content.splitlines()
            ):
                raise ValueError("revision must contain Markdown headings")

    def _candidate_for_task(self, task: OptimizationTask, candidate_id: str) -> CandidateDraft:
        candidate = self.candidates.get(candidate_id)
        if (
            candidate.assignment_id != task.assignment_id
            or candidate.conversation_id != task.conversation_id
        ):
            raise ValueError("candidate does not belong to optimization task context")
        return candidate

    def _write(self, task: OptimizationTask) -> None:
        self._store.write_yaml(self._path(task), task.model_dump(mode="json"))

    @staticmethod
    def _updated(task: OptimizationTask, **changes: object) -> OptimizationTask:
        return OptimizationTask.model_validate({**task.model_dump(mode="json"), **changes})

    @staticmethod
    def _path(task: OptimizationTask) -> str:
        return f"assignments/{task.assignment_id}/optimization-tasks/{task.id}.yaml"

    @staticmethod
    def _direction_metadata_path(task: OptimizationTask) -> str:
        return f"assignments/{task.assignment_id}/optimization-directions/{task.id}/attachment.yaml"
