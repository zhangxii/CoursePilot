"""Testable main-agent orchestration with specialist agents kept as tools."""

from pathlib import Path
from typing import Protocol

from agents import Agent, SQLiteSession
from pydantic import BaseModel, ConfigDict

from coursepilot.models import (
    AgentKind,
    AssignmentResult,
    CourseContext,
    MainAgentResult,
    NotesResult,
    ReviewResult,
    RevisionResult,
)
from coursepilot.observability import TraceCollector, TraceContext


class CourseRequiredError(ValueError):
    """Raised instead of guessing a missing active course."""


class UnknownIntentError(ValueError):
    """Raised when the request cannot be mapped safely."""


class AgentRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    message: str
    context: CourseContext


class SpecialistResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: AgentKind
    message: str


class SpecialistGateway(Protocol):
    async def run(self, kind: AgentKind, request: AgentRequest) -> SpecialistResult: ...


class MainAgent:
    def __init__(self, specialists: SpecialistGateway, trace: TraceCollector | None = None) -> None:
        self._specialists = specialists
        self._trace = trace

    async def run(self, message: str, context: CourseContext | None) -> MainAgentResult:
        if context is None:
            raise CourseRequiredError("请先选择当前课程")
        trace_context = TraceContext.create("agent-run", context.active_course_id)
        intent = _classify(message)
        sequence = [intent]
        if intent is AgentKind.REVISION and context.latest_review is None:
            sequence = [AgentKind.REVIEW, AgentKind.REVISION]
        outputs = []
        for kind in sequence:
            request = AgentRequest(message=message, context=context)
            if self._trace is None:
                output = await self._specialists.run(kind, request)
            else:
                with self._trace.span(
                    trace_context, "specialist_agent", intent=intent.value, agent=kind.value
                ):
                    output = await self._specialists.run(kind, request)
            outputs.append(output)
        return MainAgentResult(
            intent=intent,
            invoked_agents=sequence,
            final_response="\n".join(output.message for output in outputs),
            context=context,
        )


def _classify(message: str) -> AgentKind:
    normalized = message.strip().lower()
    rules = (
        (AgentKind.REVISION, ("修改", "优化", "revision", "revise")),
        (AgentKind.REVIEW, ("评审", "评分", "review")),
        (AgentKind.ASSIGNMENT, ("作业", "答案", "assignment")),
        (AgentKind.NOTES, ("总结", "笔记", "notes", "summary")),
    )
    for kind, keywords in rules:
        if any(keyword in normalized for keyword in keywords):
            return kind
    raise UnknownIntentError("无法可靠识别任务，请说明要总结、完成、评审还是修改")


class SqliteAgentRuntime:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)

    def session(self, session_id: str) -> SQLiteSession:
        return SQLiteSession(session_id, self._database_path)


def build_sdk_main_agent(model: str) -> Agent[None]:
    """Build the production Agents SDK graph using specialists as tools, not handoffs."""
    specialists = [
        Agent(
            name="NotesAgent",
            model=model,
            instructions="先检索当前课程并生成结构化笔记。",
            output_type=NotesResult,
        ),
        Agent(
            name="AssignmentAgent",
            model=model,
            instructions="读取唯一作业和当前答案，检索当前课程，生成并自检答案。",
            output_type=AssignmentResult,
        ),
        Agent(
            name="ReviewAgent",
            model=model,
            instructions="独立评审给定答案，不接收生成过程，只引用允许的课程证据。",
            output_type=ReviewResult,
        ),
        Agent(
            name="RevisionAgent",
            model=model,
            instructions="仅在已有答案和评审时按指定模式修改并复查问题。",
            output_type=RevisionResult,
        ),
    ]
    return Agent(
        name="CoursePilotMainAgent",
        model=model,
        instructions=(
            "识别总结、完成、评审、修改意图；当前课程不明确时询问，不猜测。"
            "专业 Agent 只能作为工具调用，最终控制权和响应整合由你保留。"
        ),
        tools=[
            agent.as_tool(
                tool_name=agent.name.lower(),
                tool_description=f"Run the {agent.name} specialist",
            )
            for agent in specialists
        ],
        output_type=MainAgentResult,
    )
