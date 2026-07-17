"""Conversation lifecycle, version binding, and branch snapshots."""

from coursepilot.agent_runtime import FileAgentRuntime, JsonlSession
from coursepilot.models import Conversation
from coursepilot.repositories import ConversationRepository
from coursepilot.services.workspace import WorkspaceService


class ConversationService:
    def __init__(
        self,
        repository: ConversationRepository,
        workspace: WorkspaceService,
        runtime: FileAgentRuntime,
    ) -> None:
        self._repository = repository
        self._workspace = workspace
        self._runtime = runtime

    def create(
        self,
        title: str,
        *,
        inherit_current_answer: bool = True,
        base_answer_version_id: str | None = None,
    ) -> Conversation:
        assignment = self._workspace.get_assignment()
        current = self._workspace.latest_answer() if inherit_current_answer else None
        selected_base = base_answer_version_id or (None if current is None else current.id)
        if selected_base is not None:
            answer = self._workspace.get_answer(selected_base)
            if answer.assignment_id != assignment.id:
                raise ValueError("base answer does not belong to the active assignment")
        return self._repository.create(
            assignment.id,
            title,
            selected_base,
        )

    def create_blank(self, title: str) -> Conversation:
        return self.create(title, inherit_current_answer=False)

    def create_from_version(self, title: str, answer_version_id: str) -> Conversation:
        return self.create(
            title,
            inherit_current_answer=False,
            base_answer_version_id=answer_version_id,
        )

    def ensure_active(self) -> Conversation:
        try:
            return self.active()
        except KeyError:
            return self.create("作业协作")

    def list(self, *, include_archived: bool = True) -> list[Conversation]:
        return self._repository.list(
            self._workspace.get_assignment().id, include_archived=include_archived
        )

    def get(self, conversation_id: str) -> Conversation:
        return self._repository.get(self._workspace.get_assignment().id, conversation_id)

    def active(self) -> Conversation:
        return self._repository.active(self._workspace.get_assignment().id)

    def activate(self, conversation_id: str) -> Conversation:
        return self._repository.activate(self._workspace.get_assignment().id, conversation_id)

    def rename(self, conversation_id: str, title: str) -> Conversation:
        return self._repository.rename(self._workspace.get_assignment().id, conversation_id, title)

    def archive(self, conversation_id: str) -> Conversation:
        return self._repository.archive(self._workspace.get_assignment().id, conversation_id)

    async def branch(
        self, parent_conversation_id: str, forked_from_message_id: str, title: str
    ) -> Conversation:
        parent = self.get(parent_conversation_id)
        items = await self.session(parent.id).get_items()
        snapshot: list[dict[str, object]] = []
        found = False
        for item in items:
            snapshot.append(item)
            if item.get("id") == forked_from_message_id:
                found = True
                break
        if not found:
            raise ValueError("conversation branch message was not found")
        return self._repository.create_branch(
            parent,
            title,
            forked_from_message_id,
            snapshot,
        )

    def session(self, conversation_id: str) -> JsonlSession:
        conversation = self.get(conversation_id)
        return self._runtime.session(f"conversation_{conversation.id.replace('-', '_')}")
