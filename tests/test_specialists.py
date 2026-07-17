import asyncio
from typing import Any

import pytest

from coursepilot.agent_runtime import NotesAgent, ReviewRequiredError, RevisionAgent
from coursepilot.models import CourseContext, NotesResult, RevisionMode
from coursepilot.reliability import ExternalServiceTimeout, with_retry
from coursepilot.retrieval import SearchResult, SearchScope


class Retrieval:
    def __init__(self) -> None:
        self.current_queries: list[str] = []

    async def current(self, query: str, context: CourseContext) -> SearchResult:
        self.current_queries.append(query)
        return SearchResult(items=[], scope=SearchScope.CURRENT, query=query)

    async def archive(self, query, reason, context):  # pragma: no cover - forbidden path
        raise AssertionError("ordinary specialist request must not search archives")


class Generator:
    def __init__(self, outputs: list[Any]) -> None:
        self.outputs = outputs
        self.tasks: list[str] = []

    async def generate(self, task: str, payload: dict[str, Any]) -> Any:
        self.tasks.append(task)
        return self.outputs.pop(0)


def context() -> CourseContext:
    return CourseContext(
        active_course_id="architecture",
        active_course_name="Architecture",
        active_assignment_id="assignment-1",
    )


def valid_notes() -> dict[str, Any]:
    return NotesResult(
        course_problem="How to design boundaries?",
        core_concepts=["Cohesion"],
        analysis_methods=["Tradeoff analysis"],
        examples=["CoursePilot"],
        common_mistakes=["Shared mutable state"],
        teacher_criteria=["Explain rationale"],
        practical_uses=["Module design"],
        prerequisite_relationships=[],
        sources=[],
    ).model_dump(mode="json")


def test_notes_agent_searches_current_first_and_repairs_output_once() -> None:
    retrieval = Retrieval()
    generator = Generator([{"invalid": True}, valid_notes()])

    result = asyncio.run(NotesAgent(retrieval, generator).run("module boundaries", context()))

    assert result.course_problem == "How to design boundaries?"
    assert retrieval.current_queries == ["module boundaries"]
    assert generator.tasks == ["notes", "repair_notes"]


def test_revision_agent_refuses_to_rewrite_without_review() -> None:
    with pytest.raises(ReviewRequiredError):
        asyncio.run(
            RevisionAgent(Retrieval(), Generator([])).run(
                "revise", context(), RevisionMode.DEEP_RESTRUCTURE
            )
        )


def test_external_retry_is_bounded_and_returns_friendly_timeout() -> None:
    calls = 0

    async def unavailable() -> str:
        nonlocal calls
        calls += 1
        raise ConnectionError("offline")

    with pytest.raises(ExternalServiceTimeout, match="2 次尝试"):
        asyncio.run(with_retry(unavailable, attempts=2, timeout_seconds=0.1))

    assert calls == 2
