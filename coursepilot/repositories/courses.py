"""YAML-backed course repository."""

import re
import threading
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from coursepilot.file_store import FileDataStore, dump_yaml
from coursepilot.models import Course


class CourseIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_course_id: str | None
    course_ids: list[str]


class CourseRepository:
    _lock = threading.RLock()

    def __init__(self, data_root: str | Path) -> None:
        self._store = FileDataStore(Path(data_root))

    def add(
        self,
        *,
        course_id: str,
        name: str,
        course_date: date,
        teacher: str,
        topic: str,
        active: bool,
    ) -> Course:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", course_id):
            raise ValueError("course_id may contain only letters, numbers, underscore and hyphen")
        course = Course(
            id=course_id,
            name=name,
            course_date=course_date,
            teacher=teacher,
            topic=topic,
            is_active=active,
        )
        with self._lock:
            path = self._course_path(course_id)
            if self._store.exists(path):
                raise ValueError(f"course already exists: {course_id}")
            course_data = {
                "id": course.id,
                "name": course.name,
                "course_date": course.course_date.isoformat(),
                "teacher": course.teacher,
                "topic": course.topic,
            }
            index = self._index()
            index.course_ids.append(course_id)
            if active or index.active_course_id is None:
                index.active_course_id = course_id
            self._store.write_batch(
                {
                    path: dump_yaml(course_data),
                    "courses/course-index.yaml": dump_yaml(index.model_dump(mode="json")),
                }
            )
        return self.get(course_id)

    def get(self, course_id: str) -> Course:
        data = self._store.read_yaml(self._course_path(course_id))
        if data is None:
            raise KeyError(course_id)
        return Course(
            id=data["id"],
            name=data["name"],
            course_date=data["course_date"],
            teacher=data["teacher"],
            topic=data["topic"],
            is_active=self._index().active_course_id == course_id,
        )

    def list(self) -> list[Course]:
        courses = [self.get(course_id) for course_id in self._index().course_ids]
        return sorted(courses, key=lambda item: (item.course_date, item.id), reverse=True)

    def get_active(self) -> Course | None:
        active = self._index().active_course_id
        return None if active is None else self.get(active)

    def activate(self, course_id: str) -> Course:
        with self._lock:
            self.get(course_id)
            index = self._index()
            index.active_course_id = course_id
            self._store.write_yaml("courses/course-index.yaml", index.model_dump(mode="json"))
        return self.get(course_id)

    def _index(self) -> CourseIndex:
        data = self._store.read_yaml(
            "courses/course-index.yaml",
            {"active_course_id": None, "course_ids": []},
        )
        return CourseIndex.model_validate(data)

    @staticmethod
    def _course_path(course_id: str) -> str:
        return f"courses/{course_id}/course.yaml"
