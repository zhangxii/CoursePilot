import asyncio

import pytest

from coursepilot.models import (
    CourseContext,
    MaterialSearchAttributes,
    MaterialStatus,
    MaterialType,
)
from coursepilot.retrieval import (
    ArchiveSearchReason,
    ComparisonFilter,
    CompoundFilter,
    CurrentFirstPolicy,
    InvalidArchiveSearchReason,
    MaterialSearchHit,
    MemoryTraceRecorder,
    SearchScope,
    merge_evidence,
    search_course_archive,
    search_current_course,
)


class FakeSearchGateway:
    def __init__(self, hits: list[MaterialSearchHit]) -> None:
        self.hits = hits
        self.calls: list[tuple[str, ComparisonFilter | CompoundFilter, int]] = []

    async def search(
        self,
        query: str,
        filters: ComparisonFilter | CompoundFilter,
        max_results: int,
    ) -> list[MaterialSearchHit]:
        self.calls.append((query, filters, max_results))
        return self.hits


class FailingSearchGateway:
    async def search(
        self,
        query: str,
        filters: ComparisonFilter | CompoundFilter,
        max_results: int,
    ) -> list[MaterialSearchHit]:
        raise RuntimeError("search unavailable")


def context() -> CourseContext:
    return CourseContext(
        active_course_id="architecture-20260717",
        active_course_name="架构设计",
    )


def hit(course_id: str, status: str = "current") -> MaterialSearchHit:
    return MaterialSearchHit(
        file_id="file-1",
        filename="architecture.md",
        score=0.91,
        attributes=MaterialSearchAttributes(
            course_id=course_id,
            course_name="Architecture",
            course_date="2026-07-17",
            teacher="Teacher",
            topic="Architecture",
            material_type=MaterialType.PDF,
            status=MaterialStatus(status),
        ),
        text="## PDF 第 12 页\n\n模块应当具有清晰边界。",
    )


def test_current_course_search_forces_active_course_filter_and_returns_sources() -> None:
    gateway = FakeSearchGateway(
        [hit("architecture-20260717"), hit("requirements-20260701", "archived")]
    )
    trace = MemoryTraceRecorder()

    result = asyncio.run(
        search_current_course("模块边界", context(), gateway=gateway, max_results=5, trace=trace)
    )

    assert result.scope is SearchScope.CURRENT
    assert result.items[0].source.course_id == "architecture-20260717"
    assert len(result.items) == 1
    assert result.items[0].source.page_or_section == "PDF 第 12 页"
    assert gateway.calls == [
        (
            "模块边界",
            ComparisonFilter(type="eq", key="course_id", value="architecture-20260717"),
            5,
        )
    ]
    assert trace.events[0].attributes["active_course_id"] == "architecture-20260717"


def test_archive_search_excludes_active_course_and_records_reason() -> None:
    gateway = FakeSearchGateway(
        [hit("requirements-20260701", "archived"), hit("architecture-20260717")]
    )
    trace = MemoryTraceRecorder()

    result = asyncio.run(
        search_course_archive(
            "前序需求",
            ArchiveSearchReason.PREREQUISITE_REFERENCED,
            context(),
            gateway=gateway,
            max_results=3,
            trace=trace,
        )
    )

    assert result.scope is SearchScope.ARCHIVE
    assert result.reason is ArchiveSearchReason.PREREQUISITE_REFERENCED
    assert [item.source.course_id for item in result.items] == ["requirements-20260701"]
    assert gateway.calls[0][1] == CompoundFilter(
        type="and",
        filters=[
            ComparisonFilter(type="ne", key="course_id", value="architecture-20260717"),
            ComparisonFilter(type="eq", key="status", value="archived"),
        ],
    )
    assert trace.events[0].attributes["reason"] == "prerequisite_referenced"


def test_archive_search_rejects_missing_or_unrecognised_reason() -> None:
    gateway = FakeSearchGateway([])

    with pytest.raises(InvalidArchiveSearchReason):
        asyncio.run(
            search_course_archive(
                "history",
                "because I want it",  # type: ignore[arg-type]
                context(),
                gateway=gateway,
            )
        )

    assert gateway.calls == []


def test_archive_search_traces_approved_reason_even_when_gateway_fails() -> None:
    trace = MemoryTraceRecorder()

    with pytest.raises(RuntimeError, match="search unavailable"):
        asyncio.run(
            search_course_archive(
                "history",
                ArchiveSearchReason.USER_REQUESTED,
                context(),
                gateway=FailingSearchGateway(),
                trace=trace,
            )
        )

    assert trace.events[0].attributes["reason"] == "user_requested"


def test_merge_keeps_current_course_first_and_marks_cross_course_conflict() -> None:
    current_gateway = FakeSearchGateway([hit("architecture-20260717")])
    archive_gateway = FakeSearchGateway([hit("requirements-20260701", "archived")])
    current = asyncio.run(search_current_course("standard", context(), gateway=current_gateway))
    archive = asyncio.run(
        search_course_archive(
            "standard",
            ArchiveSearchReason.USER_REQUESTED,
            context(),
            gateway=archive_gateway,
        )
    )
    archive = archive.model_copy(
        update={
            "items": [
                archive.items[0].model_copy(
                    update={
                        "source": archive.items[0].source.model_copy(
                            update={"excerpt": "Historical conflicting standard"}
                        )
                    }
                )
            ]
        }
    )

    merged = merge_evidence(current, archive)

    assert merged.items[0].source.course_id == "architecture-20260717"
    assert merged.has_cross_course_conflict is True


def test_archive_permission_requires_current_search_first() -> None:
    policy = CurrentFirstPolicy()

    with pytest.raises(ValueError, match="prior current-course search"):
        policy.authorize_archive(ArchiveSearchReason.CURRENT_EVIDENCE_INSUFFICIENT)

    policy.record_current_search()
    policy.authorize_archive(ArchiveSearchReason.CURRENT_EVIDENCE_INSUFFICIENT)
