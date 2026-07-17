"""Safe filesystem boundary for Markdown course-material bodies."""

from pathlib import Path


class MaterialFileStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def write(self, material_id: str, content: str) -> str:
        if not content.strip():
            raise ValueError("material content must not be blank")
        key = Path(material_id) / "content.md"
        destination = self._resolve(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(destination)
        return key.as_posix()

    def read(self, storage_key: str) -> str:
        if not storage_key.strip():
            raise ValueError("material storage key must not be blank")
        return self._resolve(Path(storage_key)).read_text(encoding="utf-8")

    def exists(self, storage_key: str) -> bool:
        if not storage_key.strip():
            return False
        try:
            return self._resolve(Path(storage_key)).is_file()
        except ValueError:
            return False

    def _resolve(self, key: Path) -> Path:
        if key.is_absolute():
            raise ValueError("material storage key must be relative")
        target = (self._root / key).resolve()
        if not target.is_relative_to(self._root):
            raise ValueError("material storage key escapes the material root")
        return target
