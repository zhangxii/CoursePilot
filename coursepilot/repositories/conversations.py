"""File-backed conversation metadata isolated per assignment."""

import json
import threading
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from coursepilot.file_store import FileDataStore, dump_yaml
from coursepilot.models import Conversation, ConversationStatus


class ConversationIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_conversation_id: str | None = None
    conversation_ids: list[str] = Field(default_factory=list)


class ConversationRepository:
    _lock = threading.RLock()

    def __init__(self, data_root: str | Path) -> None:
        self._store = FileDataStore(Path(data_root))

    def create(
        self,
        assignment_id: str,
        title: str,
        base_answer_version_id: str | None,
        *,
        parent_conversation_id: str | None = None,
        forked_from_message_id: str | None = None,
    ) -> Conversation:
        conversation = Conversation(
            id=str(uuid4()),
            assignment_id=assignment_id,
            title=title,
            base_answer_version_id=base_answer_version_id,
            parent_conversation_id=parent_conversation_id,
            forked_from_message_id=forked_from_message_id,
        )
        with self._lock:
            index = self._index(assignment_id)
            index.conversation_ids.append(conversation.id)
            index.active_conversation_id = conversation.id
            self._store.write_batch(
                {
                    self._path(assignment_id, conversation.id): self._yaml(conversation),
                    self._index_path(assignment_id): self._yaml(index),
                }
            )
        return conversation

    def create_branch(
        self,
        parent: Conversation,
        title: str,
        forked_from_message_id: str,
        snapshot: list[dict[str, object]],
    ) -> Conversation:
        """Commit branch metadata, active pointer, and message snapshot together."""
        conversation = Conversation(
            id=str(uuid4()),
            assignment_id=parent.assignment_id,
            team_id=parent.team_id,
            title=title,
            base_answer_version_id=parent.base_answer_version_id,
            parent_conversation_id=parent.id,
            forked_from_message_id=forked_from_message_id,
        )
        session_id = f"conversation_{conversation.id.replace('-', '_')}"
        serialized = "".join(f"{json.dumps(item, ensure_ascii=False)}\n" for item in snapshot)
        with self._lock:
            index = self._index(parent.assignment_id)
            index.conversation_ids.append(conversation.id)
            index.active_conversation_id = conversation.id
            self._store.write_batch(
                {
                    self._path(parent.assignment_id, conversation.id): self._yaml(conversation),
                    self._index_path(parent.assignment_id): self._yaml(index),
                    f"sessions/{session_id}.jsonl": serialized,
                }
            )
        return conversation

    def get(self, assignment_id: str, conversation_id: str) -> Conversation:
        data = self._store.read_yaml(self._path(assignment_id, conversation_id))
        if data is None:
            raise KeyError(conversation_id)
        return Conversation.model_validate(data)

    def list(self, assignment_id: str, *, include_archived: bool = True) -> list[Conversation]:
        conversations = [
            self.get(assignment_id, item) for item in self._index(assignment_id).conversation_ids
        ]
        return (
            conversations
            if include_archived
            else [item for item in conversations if item.status is ConversationStatus.ACTIVE]
        )

    def active(self, assignment_id: str) -> Conversation:
        active_id = self._index(assignment_id).active_conversation_id
        if active_id is None:
            raise KeyError("active_conversation")
        return self.get(assignment_id, active_id)

    def activate(self, assignment_id: str, conversation_id: str) -> Conversation:
        with self._lock:
            conversation = self.get(assignment_id, conversation_id)
            if conversation.status is ConversationStatus.ARCHIVED:
                raise ValueError("archived conversation cannot be activated")
            index = self._index(assignment_id)
            index.active_conversation_id = conversation.id
            self._store.write_yaml(self._index_path(assignment_id), index.model_dump(mode="json"))
            return conversation

    def rename(self, assignment_id: str, conversation_id: str, title: str) -> Conversation:
        with self._lock:
            conversation = self.get(assignment_id, conversation_id)
            renamed = conversation.model_copy(update={"title": title})
            validated = Conversation.model_validate(renamed.model_dump(mode="json"))
            self._store.write_yaml(
                self._path(assignment_id, conversation_id), validated.model_dump(mode="json")
            )
            return validated

    def archive(self, assignment_id: str, conversation_id: str) -> Conversation:
        with self._lock:
            conversation = self.get(assignment_id, conversation_id)
            archived = Conversation.model_validate(
                {**conversation.model_dump(mode="json"), "status": ConversationStatus.ARCHIVED}
            )
            index = self._index(assignment_id)
            if index.active_conversation_id == conversation_id:
                alternatives = [
                    item
                    for item in self.list(assignment_id, include_archived=False)
                    if item.id != conversation_id
                ]
                index.active_conversation_id = None if not alternatives else alternatives[-1].id
            self._store.write_batch(
                {
                    self._path(assignment_id, conversation_id): self._yaml(archived),
                    self._index_path(assignment_id): self._yaml(index),
                }
            )
            return archived

    def _index(self, assignment_id: str) -> ConversationIndex:
        return ConversationIndex.model_validate(
            self._store.read_yaml(
                self._index_path(assignment_id),
                {"active_conversation_id": None, "conversation_ids": []},
            )
        )

    @staticmethod
    def _path(assignment_id: str, conversation_id: str) -> str:
        return f"assignments/{assignment_id}/conversations/{conversation_id}.yaml"

    @staticmethod
    def _index_path(assignment_id: str) -> str:
        return f"assignments/{assignment_id}/conversations/index.yaml"

    @staticmethod
    def _yaml(model: BaseModel) -> str:
        return dump_yaml(model.model_dump(mode="json"))
