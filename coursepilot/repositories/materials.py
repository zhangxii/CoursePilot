"""Markdown-front-matter-backed course material repository."""

import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from coursepilot.file_store import FileDataStore, parse_front_matter, render_front_matter
from coursepilot.models import (
    IndexStatus,
    LocalMaterialDocument,
    MaterialMetadata,
    MaterialRecord,
    MaterialStatus,
    MaterialType,
)
from coursepilot.repositories.courses import CourseRepository


class MaterialRepository:
    _lock = threading.RLock()

    def __init__(self, data_root: str | Path) -> None:
        self._root = Path(data_root)
        self._store = FileDataStore(self._root)
        self._courses = CourseRepository(self._root)

    def add(
        self,
        metadata: MaterialMetadata,
        *,
        file_name: str,
        file_hash: str,
        body: str,
    ) -> MaterialRecord:
        with self._lock:
            course = self._courses.get(metadata.course_id)
            if body.startswith("---\n"):
                _, body = parse_front_matter(body)
            existing = self.find_by_course_hash(metadata.course_id, file_hash)
            if existing is not None:
                return existing
            material_id = str(uuid4())
            storage_path = f"courses/{metadata.course_id}/materials/{material_id}.md"
            front_matter = {
                "id": material_id,
                "course_id": metadata.course_id,
                "course_name": course.name,
                "course_date": course.course_date.isoformat(),
                "teacher": course.teacher,
                "topic": course.topic,
                "title": Path(file_name).stem,
                "original_file_name": file_name,
                "source_type": metadata.material_type.value,
                "content_hash": file_hash,
                "uploaded_at": datetime.now(UTC).isoformat(),
            }
            self._store.write_text(storage_path, render_front_matter(front_matter, body))
            return self.get(material_id)

    def find_by_course_hash(self, course_id: str, file_hash: str) -> MaterialRecord | None:
        return next(
            (item for item in self.list_for_course(course_id) if item.file_hash == file_hash),
            None,
        )

    def get(self, material_id: str) -> MaterialRecord:
        for path in self._store.glob("courses/*/materials/*.md"):
            metadata, _ = parse_front_matter(path.read_text(encoding="utf-8"))
            if metadata.get("id") == material_id:
                return self._to_record(path, metadata)
        raise KeyError(material_id)

    def list_for_course(self, course_id: str) -> list[MaterialRecord]:
        return [
            self._to_record(path, parse_front_matter(path.read_text(encoding="utf-8"))[0])
            for path in self._store.glob(f"courses/{course_id}/materials/*.md")
        ]

    def list_indexed_documents(self) -> list[LocalMaterialDocument]:
        return [
            LocalMaterialDocument(
                material=material,
                course_name=course.name,
                course_date=course.course_date,
                teacher=course.teacher,
                topic=course.topic,
            )
            for course in self._courses.list()
            for material in self.list_for_course(course.id)
        ]

    def read_body(self, material: MaterialRecord) -> str:
        _, body = parse_front_matter(self._store.read_text(material.storage_path))
        return body

    def _to_record(self, path: Path, metadata: dict[str, object]) -> MaterialRecord:
        active = self._courses.get_active()
        course_id = str(metadata["course_id"])
        relative = path.resolve().relative_to(self._store.root).as_posix()
        return MaterialRecord(
            id=str(metadata["id"]),
            course_id=course_id,
            file_name=str(metadata["original_file_name"]),
            file_hash=str(metadata["content_hash"]),
            material_type=MaterialType(str(metadata["source_type"])),
            status=(
                MaterialStatus.CURRENT
                if active is not None and active.id == course_id
                else MaterialStatus.ARCHIVED
            ),
            index_status=IndexStatus.INDEXED,
            storage_path=relative,
        )
