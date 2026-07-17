"""Retrieval tools with hard current/archive course boundaries."""

import re
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from coursepilot.models import CourseContext, SourceRef

FilterValue = str | float | bool


class ArchiveSearchReason(StrEnum):
    USER_REQUESTED = "user_requested"
    PREREQUISITE_REFERENCED = "prerequisite_referenced"
    CURRENT_EVIDENCE_INSUFFICIENT = "current_evidence_insufficient"
    CROSS_COURSE_CONSISTENCY = "cross_course_consistency"


class SearchScope(StrEnum):
    CURRENT = "current"
    ARCHIVE = "archive"


class InvalidArchiveSearchReason(ValueError):
    """Raised when archived material search has no approved reason."""


class ComparisonFilter(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["eq", "ne"]
    key: str
    value: FilterValue


class CompoundFilter(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["and"]
    filters: Annotated[list[ComparisonFilter], Field(min_length=1)]


SearchFilter = ComparisonFilter | CompoundFilter


class RemoteSearchHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    file_id: str
    filename: str
    score: float
    attributes: dict[str, FilterValue]
    text: str


class SearchItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: SourceRef
    score: float


class SearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[SearchItem]
    scope: SearchScope
    query: str
    reason: ArchiveSearchReason | None = None


class TraceEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    attributes: dict[str, str]


class TraceRecorder(Protocol):
    def record(self, event: TraceEvent) -> None: ...


class MemoryTraceRecorder:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def record(self, event: TraceEvent) -> None:
        self.events.append(event)


class SearchGateway(Protocol):
    async def search(
        self, query: str, filters: SearchFilter, max_results: int
    ) -> list[RemoteSearchHit]: ...


async def search_current_course(
    query: str,
    context: CourseContext,
    *,
    gateway: SearchGateway,
    max_results: int = 5,
    trace: TraceRecorder | None = None,
) -> SearchResult:
    _validate_search(query, max_results)
    filters = ComparisonFilter(type="eq", key="course_id", value=context.active_course_id)
    remote_hits = await gateway.search(query, filters, max_results)
    hits = [
        item for item in remote_hits if item.attributes.get("course_id") == context.active_course_id
    ]
    result = SearchResult(
        items=[_to_search_item(hit) for hit in hits],
        scope=SearchScope.CURRENT,
        query=query,
    )
    _record(
        trace,
        "search_current_course",
        active_course_id=context.active_course_id,
        result_count=str(len(result.items)),
    )
    return result


async def search_course_archive(
    query: str,
    reason: ArchiveSearchReason,
    context: CourseContext,
    *,
    gateway: SearchGateway,
    max_results: int = 5,
    trace: TraceRecorder | None = None,
) -> SearchResult:
    if not isinstance(reason, ArchiveSearchReason):
        raise InvalidArchiveSearchReason("an approved archive search reason is required")
    _validate_search(query, max_results)
    filters = ComparisonFilter(type="ne", key="course_id", value=context.active_course_id)
    remote_hits = await gateway.search(query, filters, max_results)
    hits = [
        item for item in remote_hits if item.attributes.get("course_id") != context.active_course_id
    ]
    result = SearchResult(
        items=[_to_search_item(hit) for hit in hits],
        scope=SearchScope.ARCHIVE,
        query=query,
        reason=reason,
    )
    _record(
        trace,
        "search_course_archive",
        active_course_id=context.active_course_id,
        reason=reason.value,
        result_count=str(len(result.items)),
    )
    return result


def _validate_search(query: str, max_results: int) -> None:
    if not query.strip():
        raise ValueError("search query must not be blank")
    if max_results <= 0:
        raise ValueError("max_results must be positive")


def _to_search_item(hit: RemoteSearchHit) -> SearchItem:
    heading = re.search(r"^##\s+(.+)$", hit.text, flags=re.MULTILINE)
    page_or_section = heading.group(1).strip() if heading else "检索片段"
    return SearchItem(
        source=SourceRef(
            material_id=hit.file_id,
            file_name=hit.filename,
            course_id=str(hit.attributes["course_id"]),
            page_or_section=page_or_section,
            excerpt=hit.text,
        ),
        score=hit.score,
    )


def _record(trace: TraceRecorder | None, name: str, **attributes: str) -> None:
    if trace is not None:
        trace.record(TraceEvent(name=name, attributes=attributes))
