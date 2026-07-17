import logging

from coursepilot.agent_runtime import build_sdk_main_agent
from coursepilot.models import Assignment, Team, TeamMember
from coursepilot.observability import TraceCollector, TraceContext, log_error
from coursepilot.ui import WorkspaceView


def test_sdk_main_agent_exposes_four_specialists_as_tools() -> None:
    agent = build_sdk_main_agent("gpt-5-mini")

    assert agent.name == "CoursePilotMainAgent"
    assert {tool.name for tool in agent.tools} == {
        "notesagent",
        "assignmentagent",
        "reviewagent",
        "revisionagent",
    }
    assert agent.handoffs == []


def test_trace_correlates_spans_and_logs_redact_secrets(caplog) -> None:
    context = TraceContext.create("session-1", "architecture")
    collector = TraceCollector()

    with collector.span(context, "main_agent", intent="review"):
        pass
    with caplog.at_level(logging.ERROR):
        log_error(
            logging.getLogger("coursepilot.test"), context, RuntimeError("Bearer secret-token")
        )

    assert collector.records[0].request_id == context.request_id
    assert collector.records[0].attributes["intent"] == "review"
    assert "secret-token" not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_workspace_view_has_one_assignment_and_no_create_entry() -> None:
    view = WorkspaceView(
        team=Team(name="Group", members=[TeamMember(id="alice", name="Alice")]),
        courses=[],
        assignments=[
            Assignment(
                id="assignment-1",
                title="First assignment",
                requirements="Deliver one report",
            )
        ],
        assignment=Assignment(
            id="assignment-1",
            title="First assignment",
            requirements="Deliver one report",
        ),
        answer=None,
        answer_version=1,
        review=None,
        materials=[],
    )

    assert view.assignment.id == "assignment-1"
    assert view.can_create_assignment is True
    assert view.active_course is None
