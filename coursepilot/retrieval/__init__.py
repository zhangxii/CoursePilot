"""Policy-enforced current and archived course retrieval."""

from coursepilot.retrieval.search import (
    ArchiveSearchReason,
    ComparisonFilter,
    CompoundFilter,
    InvalidArchiveSearchReason,
    MemoryTraceRecorder,
    RemoteSearchHit,
    SearchGateway,
    SearchItem,
    SearchResult,
    SearchScope,
    TraceEvent,
    TraceRecorder,
    search_course_archive,
    search_current_course,
)

__all__ = [
    "ArchiveSearchReason",
    "ComparisonFilter",
    "CompoundFilter",
    "InvalidArchiveSearchReason",
    "MemoryTraceRecorder",
    "RemoteSearchHit",
    "SearchGateway",
    "SearchItem",
    "SearchResult",
    "SearchScope",
    "TraceEvent",
    "TraceRecorder",
    "search_course_archive",
    "search_current_course",
]
