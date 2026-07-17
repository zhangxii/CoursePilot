"""Professional-agent policies with retrieval and model boundaries injected."""

from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from coursepilot.models import (
    AssignmentResult,
    CourseContext,
    NotesResult,
    ReviewResult,
    RevisionMode,
    RevisionResult,
)
from coursepilot.retrieval import ArchiveSearchReason, SearchResult


class StructuredOutputError(RuntimeError):
    """Raised after the bounded structured-output repair attempt fails."""


class ReviewRequiredError(ValueError):
    """Raised when revision is requested without a review."""


class RetrievalTools(Protocol):
    async def current(self, query: str, context: CourseContext) -> SearchResult: ...

    async def archive(
        self, query: str, reason: ArchiveSearchReason, context: CourseContext
    ) -> SearchResult: ...


class StructuredGenerator(Protocol):
    async def generate(self, task: str, payload: dict[str, Any]) -> Any: ...


async def _validated[OutputT: BaseModel](
    generator: StructuredGenerator,
    output_type: type[OutputT],
    task: str,
    payload: dict[str, Any],
) -> OutputT:
    candidate = await generator.generate(task, payload)
    try:
        return output_type.model_validate(candidate)
    except ValidationError as first_error:
        repaired = await generator.generate(
            f"repair_{task}", {"invalid_output": candidate, "error": str(first_error)}
        )
        try:
            return output_type.model_validate(repaired)
        except ValidationError as error:
            raise StructuredOutputError(f"{task} 输出校验失败") from error


class NotesAgent:
    def __init__(self, retrieval: RetrievalTools, generator: StructuredGenerator) -> None:
        self._retrieval = retrieval
        self._generator = generator

    async def run(self, query: str, context: CourseContext) -> NotesResult:
        current = await self._retrieval.current(query, context)
        return await _validated(
            self._generator,
            NotesResult,
            "notes",
            {"query": query, "current_evidence": current.model_dump(mode="json")},
        )


class AssignmentAgent:
    def __init__(self, retrieval: RetrievalTools, generator: StructuredGenerator) -> None:
        self._retrieval = retrieval
        self._generator = generator

    async def run(
        self, query: str, context: CourseContext, assignment: dict[str, Any]
    ) -> AssignmentResult:
        current = await self._retrieval.current(query, context)
        return await _validated(
            self._generator,
            AssignmentResult,
            "assignment",
            {
                "assignment": assignment,
                "current_answer": context.current_answer,
                "current_evidence": current.model_dump(mode="json"),
                "self_check_required": True,
            },
        )


class ReviewAgent:
    def __init__(self, retrieval: RetrievalTools, generator: StructuredGenerator) -> None:
        self._retrieval = retrieval
        self._generator = generator

    async def run(
        self, query: str, context: CourseContext, assignment: dict[str, Any]
    ) -> ReviewResult:
        current = await self._retrieval.current(query, context)
        return await _validated(
            self._generator,
            ReviewResult,
            "review",
            {
                "assignment": assignment,
                "answer": context.current_answer,
                "current_evidence": current.model_dump(mode="json"),
            },
        )


class RevisionAgent:
    def __init__(self, retrieval: RetrievalTools, generator: StructuredGenerator) -> None:
        self._retrieval = retrieval
        self._generator = generator

    async def run(self, query: str, context: CourseContext, mode: RevisionMode) -> RevisionResult:
        if context.current_answer is None or context.latest_review is None:
            raise ReviewRequiredError("修改前必须存在当前答案及对应评审")
        current = await self._retrieval.current(query, context)
        return await _validated(
            self._generator,
            RevisionResult,
            "revision",
            {
                "mode": mode.value,
                "answer": context.current_answer,
                "review": context.latest_review.model_dump(mode="json"),
                "current_evidence": current.model_dump(mode="json"),
            },
        )
