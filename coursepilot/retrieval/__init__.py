"""Policy-enforced current and archived course retrieval."""

from coursepilot.retrieval.policy import CurrentFirstPolicy
from coursepilot.retrieval.search import (
    ArchiveSearchReason,
    ComparisonFilter,
    CompoundFilter,
    EvidenceSet,
    InvalidArchiveSearchReason,
    MemoryTraceRecorder,
    RemoteSearchHit,
    SearchGateway,
    SearchItem,
    SearchResult,
    SearchScope,
    TraceEvent,
    TraceRecorder,
    merge_evidence,
    search_course_archive,
    search_current_course,
)

__all__ = [
    "ArchiveSearchReason",
    "ComparisonFilter",
    "CurrentFirstPolicy",
    "CompoundFilter",
    "EvidenceSet",
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
    "merge_evidence",
]
