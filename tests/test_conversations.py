import asyncio
from datetime import date
from pathlib import Path

import pytest

from coursepilot.agent_runtime import FileAgentRuntime
from coursepilot.file_store import FileDataStore
from coursepilot.models import (
    AgentKind,
    AssignmentResult,
    AssignmentUploadPurpose,
    ConversationStatus,
    Course,
    MainAgentResult,
    TeamMember,
)
from coursepilot.repositories import ConversationRepository, WorkspaceRepository
from coursepilot.services import (
    AssignmentArtifactService,
    ConversationService,
    WorkspaceService,
)


def setup_workspace(data_root: Path) -> tuple[WorkspaceService, AssignmentArtifactService]:
    workspace = WorkspaceService(WorkspaceRepository(data_root))
    workspace.initialize_team("Group", [TeamMember(id="alice", name="Alice")])
    workspace.initialize_assignment("Report", "Write the report")
    artifacts = AssignmentArtifactService(data_root, workspace)
    return workspace, artifacts


def test_new_conversations_bind_the_current_formal_version_without_sharing_messages(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    workspace, artifacts = setup_workspace(data_root)
    first = artifacts.import_assignment(
        "v1.txt",
        b"Formal v1",
        AssignmentUploadPurpose.INITIAL_VERSION,
        "alice",
        "Initial",
    ).answer_version
    assert first is not None
    conversations = ConversationService(
        ConversationRepository(data_root), workspace, FileAgentRuntime(data_root)
    )
    agent_plan = conversations.create("Agent plan")
    asyncio.run(
        conversations.session(agent_plan.id).add_items(
            [{"id": "m1", "role": "user", "content": "Agent proposal"}]
        )
    )
    second = artifacts.import_assignment(
        "v2.txt",
        b"Formal v2",
        AssignmentUploadPurpose.NEW_FORMAL_VERSION,
        "alice",
        "My proposal",
    ).answer_version
    assert second is not None
    my_plan = conversations.create("My plan")

    assert agent_plan.base_answer_version_id == first.id
    assert my_plan.base_answer_version_id == second.id
    assert asyncio.run(conversations.session(my_plan.id).get_items()) == []
    assert asyncio.run(conversations.session(agent_plan.id).get_items())[0]["id"] == "m1"
    assert conversations.active().id == my_plan.id

    course = Course(
        id="course-1",
        name="Course",
        course_date=date(2026, 7, 17),
        teacher="Teacher",
        topic="Topic",
        is_active=True,
    )
    old_context = workspace.context(course, agent_plan)
    new_context = workspace.context(course, my_plan)
    assert old_context.current_answer == "Formal v1"
    assert old_context.base_answer_version_id == first.id
    assert new_context.current_answer == "Formal v2"
    assert new_context.base_answer_version_id == second.id

    output = MainAgentResult(
        intent=AgentKind.ASSIGNMENT,
        invoked_agents=[AgentKind.ASSIGNMENT],
        final_response="Candidate for the old plan",
        context=old_context,
        assignment_output=AssignmentResult(
            task_understanding="Improve the old plan",
            shared_answer="Candidate based on v1",
            course_evidence=[],
            uncertainties=[],
        ),
    )
    workspace.apply_agent_output(course, output, "alice", agent_plan)
    candidate = WorkspaceRepository(data_root).list_candidates()[0]
    assert candidate.conversation_id == agent_plan.id
    assert candidate.base_answer_version_id == first.id

    with pytest.raises(ValueError, match="conversation does not match"):
        workspace.apply_agent_output(course, output, "alice", my_plan)


def test_conversation_lifecycle_and_branch_snapshot_survive_restart(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    workspace, _ = setup_workspace(data_root)
    runtime = FileAgentRuntime(data_root)
    conversations = ConversationService(ConversationRepository(data_root), workspace, runtime)
    parent = conversations.create("Explore proposal")
    asyncio.run(
        conversations.session(parent.id).add_items(
            [
                {"id": "m1", "role": "user", "content": "one"},
                {"id": "m2", "role": "assistant", "content": "two"},
                {"id": "m3", "role": "user", "content": "three"},
            ]
        )
    )

    child = asyncio.run(conversations.branch(parent.id, "m2", "Use my proposal"))
    conversations.rename(child.id, "My proposal follow-up")
    asyncio.run(
        conversations.session(child.id).add_items(
            [{"id": "child", "role": "user", "content": "child only"}]
        )
    )
    asyncio.run(
        conversations.session(parent.id).add_items(
            [{"id": "parent", "role": "user", "content": "parent only"}]
        )
    )
    conversations.archive(parent.id)

    restored = ConversationService(
        ConversationRepository(data_root), WorkspaceService(WorkspaceRepository(data_root)), runtime
    )
    restored_child = restored.get(child.id)
    parent_items = asyncio.run(restored.session(parent.id).get_items())
    child_items = asyncio.run(restored.session(child.id).get_items())

    assert restored_child.title == "My proposal follow-up"
    assert restored_child.parent_conversation_id == parent.id
    assert restored_child.forked_from_message_id == "m2"
    assert [item["id"] for item in child_items] == ["m1", "m2", "child"]
    assert [item["id"] for item in parent_items] == ["m1", "m2", "m3", "parent"]
    assert restored.get(parent.id).status is ConversationStatus.ARCHIVED
    assert restored.active().id == child.id


def test_blank_historical_and_assignment_scoped_conversations_are_stable(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    workspace, artifacts = setup_workspace(data_root)
    first = artifacts.import_assignment(
        "v1.txt",
        b"Formal v1",
        AssignmentUploadPurpose.INITIAL_VERSION,
        "alice",
        "Initial",
    ).answer_version
    assert first is not None
    conversations = ConversationService(
        ConversationRepository(data_root), workspace, FileAgentRuntime(data_root)
    )
    blank = conversations.create_blank("Blank")
    historical = conversations.create_from_version("Historical", first.id)
    assert blank.base_answer_version_id is None
    assert historical.base_answer_version_id == first.id
    assert historical.team_id == "main_team"

    workspace.create_assignment("assignment-2", "Second", "Second task")
    second_assignment = conversations.create_blank("Second blank")
    assert conversations.active().id == second_assignment.id
    with pytest.raises(KeyError):
        conversations.get(historical.id)

    workspace.activate_assignment("assignment-1")
    assert conversations.active().id == historical.id
    switched_context = workspace.context(
        Course(
            id="course-2",
            name="Other",
            course_date=date(2026, 7, 17),
            teacher="Teacher",
            topic="Topic",
            is_active=True,
        ),
        historical,
    )
    assert switched_context.active_course_id == "course-2"
    assert switched_context.conversation_id == historical.id
    assert switched_context.base_answer_version_id == first.id


def test_branch_creation_rolls_back_metadata_pointer_and_snapshot_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "data"
    workspace, _ = setup_workspace(data_root)
    conversations = ConversationService(
        ConversationRepository(data_root), workspace, FileAgentRuntime(data_root)
    )
    parent = conversations.create("Parent")
    asyncio.run(
        conversations.session(parent.id).add_items(
            [{"id": "m1", "role": "user", "content": "branch here"}]
        )
    )
    original_apply = FileDataStore._apply_batch

    def fail_after_writes(store: FileDataStore, payload: object) -> None:
        original_apply(store, payload)
        raise OSError("simulated branch failure")

    monkeypatch.setattr(FileDataStore, "_apply_batch", fail_after_writes)
    with pytest.raises(OSError, match="simulated branch failure"):
        asyncio.run(conversations.branch(parent.id, "m1", "Child"))

    assert [item.id for item in conversations.list()] == [parent.id]
    assert conversations.active().id == parent.id
    assert len(list((data_root / "sessions").glob("conversation_*.jsonl"))) == 1
