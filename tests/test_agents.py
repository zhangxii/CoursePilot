import asyncio
from pathlib import Path

import pytest

from coursepilot.agents import (
    AgentRequest,
    CourseRequiredError,
    MainAgent,
    RuleBasedIntentClassifier,
    SpecialistResult,
    SqliteAgentRuntime,
    build_sdk_main_agent,
)
from coursepilot.models import AgentKind, CourseContext, ReviewResult
from coursepilot.observability import TraceCollector


class Specialists:
    def __init__(self) -> None:
        self.calls: list[AgentKind] = []

    async def run(self, kind: AgentKind, request: AgentRequest) -> SpecialistResult:
        self.calls.append(kind)
        if kind is AgentKind.REVIEW:
            return SpecialistResult(kind=kind, message=f"{kind.value} completed", review=_review())
        if kind is AgentKind.REVISION:
            assert request.context.latest_review is not None
            return SpecialistResult(
                kind=kind, message=f"{kind.value} completed", revised_answer="revised draft"
            )
        return SpecialistResult(kind=kind, message=f"{kind.value} completed")


def context(*, reviewed: bool = False) -> CourseContext:
    return CourseContext(
        active_course_id="architecture",
        active_course_name="Architecture",
        current_answer="draft",
        latest_review=_review() if reviewed else None,
    )


def _review() -> ReviewResult:
    from coursepilot.models import DimensionScore, ReviewResult, SourceRef

    source = SourceRef(
        material_id="m1",
        file_name="lesson.md",
        course_id="architecture",
        page_or_section="Page 1",
        excerpt="Evidence",
    )
    return ReviewResult(
        total_score=100,
        dimension_scores=[
            DimensionScore(
                dimension="correctness",
                score=100,
                max_score=100,
                deduction=0,
                location="whole answer",
                evidence=[source],
                reason="Meets requirements",
                revision_advice="Keep it precise",
            )
        ],
        strengths=["Clear"],
        critical_issues=[],
        likely_teacher_questions=[],
        revision_priorities=[],
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("总结这节课", [AgentKind.NOTES]),
        ("完成小组作业", [AgentKind.ASSIGNMENT]),
        ("评审当前答案", [AgentKind.REVIEW]),
        ("修改当前答案", [AgentKind.REVIEW, AgentKind.REVISION]),
    ],
)
def test_main_agent_routes_four_tasks_and_keeps_control(
    message: str, expected: list[AgentKind]
) -> None:
    specialists = Specialists()
    result = asyncio.run(
        MainAgent(specialists, RuleBasedIntentClassifier()).run(message, context())
    )

    assert result.invoked_agents == expected
    assert specialists.calls == expected
    assert result.final_response.endswith("completed")


def test_main_agent_does_not_guess_missing_course() -> None:
    specialists = Specialists()
    with pytest.raises(CourseRequiredError):
        asyncio.run(MainAgent(specialists, RuleBasedIntentClassifier()).run("总结课程", None))

    assert specialists.calls == []


def test_main_agent_trace_records_ordered_specialist_sequence() -> None:
    specialists = Specialists()
    trace = TraceCollector()

    asyncio.run(
        MainAgent(specialists, RuleBasedIntentClassifier(), trace).run("修改当前答案", context())
    )

    assert [record.attributes["agent"] for record in trace.records] == ["review", "revision"]


def test_sqlite_agent_runtime_restores_messages_after_restart(tmp_path: Path) -> None:
    database = tmp_path / "sessions.db"
    first = SqliteAgentRuntime(database).session("group-chat")
    asyncio.run(first.add_items([{"role": "user", "content": "remember this"}]))

    restored = SqliteAgentRuntime(database).session("group-chat")

    assert asyncio.run(restored.get_items())[0]["content"] == "remember this"


def test_sdk_runtime_connects_runner_to_persistent_session(tmp_path: Path) -> None:
    class FakeRunner:
        @staticmethod
        async def run(agent, message, *, session):
            await session.add_items([{"role": "user", "content": message}])
            return "done"

    runtime = SqliteAgentRuntime(tmp_path / "sessions.db")

    result = asyncio.run(
        runtime.run(build_sdk_main_agent("gpt-5-mini"), "hello", "group", runner=FakeRunner)
    )

    assert result == "done"
    assert asyncio.run(runtime.session("group").get_items())[0]["content"] == "hello"
