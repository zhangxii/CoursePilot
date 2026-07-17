"""Validation helpers for user-prepared Markdown course materials."""

import hashlib
from pathlib import Path

from coursepilot.models import MaterialType


class UnsupportedFileType(ValueError):
    """Raised when an uploaded course material is not Markdown."""


class FileTooLarge(ValueError):
    """Raised when an uploaded file exceeds the configured limit."""


class EmptyMarkdown(ValueError):
    """Raised when a Markdown material contains no text."""


class MarkdownValidator:
    def __init__(self, *, max_upload_bytes: int) -> None:
        if max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")
        self._max_upload_bytes = max_upload_bytes

    def validate(self, path: Path) -> MaterialType:
        extension = path.suffix.casefold()
        material_types = {".md": MaterialType.MARKDOWN, ".txt": MaterialType.TEXT}
        if extension not in material_types:
            raise UnsupportedFileType(f"unsupported file extension: {path.suffix.casefold()}")
        if path.stat().st_size > self._max_upload_bytes:
            raise FileTooLarge(f"file exceeds {self._max_upload_bytes} bytes")
        if not path.read_text(encoding="utf-8").strip():
            raise EmptyMarkdown(f"Markdown file is empty: {path.name}")
        return material_types[extension]


def calculate_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
