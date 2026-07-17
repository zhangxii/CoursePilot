"""Atomic, locked and path-safe storage for YAML and Markdown files."""

import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml


class FileDataStore:
    _lock = threading.RLock()

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._recover_batch()

    def path(self, relative: str | Path) -> Path:
        key = Path(relative)
        if key.is_absolute():
            raise ValueError("data path must be relative")
        target = (self.root / key).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("data path escapes the configured root")
        return target

    def exists(self, relative: str | Path) -> bool:
        with self._lock:
            return self.path(relative).is_file()

    def read_text(self, relative: str | Path) -> str:
        with self._lock:
            return self.path(relative).read_text(encoding="utf-8")

    def write_text(self, relative: str | Path, content: str) -> None:
        target = self.path(relative)
        with self._lock:
            self._atomic_write(target, content)

    def write_bytes(self, relative: str | Path, content: bytes) -> None:
        target = self.path(relative)
        with self._lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.write_bytes(content)
            temporary.replace(target)

    def write_batch(self, documents: Mapping[str, str | bytes]) -> None:
        """Durably commit a related set of files, completing it after interruption."""
        if not documents:
            return
        journal = self.path(".pending-batch.yaml")
        with self._lock:
            entries = {}
            for relative, content in documents.items():
                target = self.path(relative)
                entries[relative] = {
                    "new": content,
                    "existed": target.exists(),
                    "old": target.read_bytes() if target.exists() else None,
                }
            payload = {"entries": entries}
            self._atomic_write(journal, dump_yaml(payload))
            try:
                self._apply_batch(payload)
            except Exception:
                self._rollback_batch(payload)
                journal.unlink(missing_ok=True)
                raise
            else:
                journal.unlink()

    def read_yaml(self, relative: str | Path, default: Any = None) -> Any:
        with self._lock:
            target = self.path(relative)
            if not target.exists():
                return default
            loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
            return default if loaded is None else loaded

    def write_yaml(self, relative: str | Path, value: Any) -> None:
        content = yaml.safe_dump(
            value,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        self.write_text(relative, content)

    def update_yaml(self, relative: str | Path, updater: Callable[[Any], Any], default: Any) -> Any:
        with self._lock:
            current = self.read_yaml(relative, default)
            updated = updater(current)
            self.write_yaml(relative, updated)
            return updated

    def glob(self, pattern: str) -> list[Path]:
        with self._lock:
            return sorted(path for path in self.root.glob(pattern) if path.is_file())

    def _recover_batch(self) -> None:
        journal = self.path(".pending-batch.yaml")
        if not journal.exists():
            return
        payload = yaml.safe_load(journal.read_text(encoding="utf-8"))
        self._rollback_batch(payload)
        journal.unlink()

    def _apply_batch(self, payload: Any) -> None:
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(entries, dict):
            raise ValueError("invalid pending file transaction")
        for relative, entry in entries.items():
            content = entry.get("new") if isinstance(entry, dict) else None
            if not isinstance(relative, str) or not isinstance(content, (str, bytes)):
                raise ValueError("invalid pending file transaction entry")
            self._atomic_write_content(self.path(relative), content)

    def _rollback_batch(self, payload: Any) -> None:
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(entries, dict):
            raise ValueError("invalid pending file transaction")
        for relative, entry in entries.items():
            if not isinstance(relative, str) or not isinstance(entry, dict):
                raise ValueError("invalid pending file transaction entry")
            target = self.path(relative)
            if entry.get("existed"):
                old = entry.get("old")
                if not isinstance(old, bytes):
                    raise ValueError("invalid transaction backup")
                self._atomic_write_content(target, old)
            else:
                target.unlink(missing_ok=True)

    @staticmethod
    def _atomic_write(target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)

    @staticmethod
    def _atomic_write_content(target: Path, content: str | bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        if isinstance(content, str):
            temporary.write_text(content, encoding="utf-8")
        else:
            temporary.write_bytes(content)
        temporary.replace(target)


def render_front_matter(metadata: dict[str, Any], body: str) -> str:
    header = dump_yaml(metadata).strip()
    return f"---\n{header}\n---\n\n{body.strip()}\n"


def parse_front_matter(document: str) -> tuple[dict[str, Any], str]:
    if not document.startswith("---\n"):
        raise ValueError("Markdown document is missing YAML front matter")
    try:
        header, body = document[4:].split("\n---\n", 1)
    except ValueError as error:
        raise ValueError("Markdown front matter is not terminated") from error
    metadata = yaml.safe_load(header)
    if not isinstance(metadata, dict):
        raise ValueError("Markdown front matter must be a mapping")
    return metadata, body.lstrip("\n")


def dump_yaml(value: Any) -> str:
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
