"""SQLite-backed course repository."""

from datetime import date
from pathlib import Path

from coursepilot.database import connect_database
from coursepilot.models import Course


class CourseRepository:
    """Persist and atomically activate courses."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

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
        status = "current" if active else "archived"
        with connect_database(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO courses (id, name, course_date, teacher, topic, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (course_id, name, course_date.isoformat(), teacher, topic, status),
            )
        return self.get(course_id)

    def get(self, course_id: str) -> Course:
        with connect_database(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT id, name, course_date, teacher, topic, status
                FROM courses WHERE id = ?
                """,
                (course_id,),
            ).fetchone()
        if row is None:
            raise KeyError(course_id)
        return self._to_model(row)

    def list(self) -> list[Course]:
        with connect_database(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, name, course_date, teacher, topic, status
                FROM courses ORDER BY course_date DESC, id
                """
            ).fetchall()
        return [self._to_model(row) for row in rows]

    def get_active(self) -> Course | None:
        with connect_database(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT id, name, course_date, teacher, topic, status
                FROM courses WHERE status = 'current'
                """
            ).fetchone()
        return None if row is None else self._to_model(row)

    def activate(self, course_id: str) -> Course:
        with connect_database(self._database_path) as connection:
            exists = connection.execute(
                "SELECT 1 FROM courses WHERE id = ?", (course_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(course_id)
            connection.execute("UPDATE courses SET status = 'archived' WHERE status = 'current'")
            connection.execute("UPDATE courses SET status = 'current' WHERE id = ?", (course_id,))
            connection.execute("UPDATE materials SET status = 'archived'")
            connection.execute(
                "UPDATE materials SET status = 'current' WHERE course_id = ?", (course_id,)
            )
        return self.get(course_id)

    @staticmethod
    def _to_model(row: tuple[str, str, str, str, str, str]) -> Course:
        return Course(
            id=row[0],
            name=row[1],
            course_date=date.fromisoformat(row[2]),
            teacher=row[3],
            topic=row[4],
            is_active=row[5] == "current",
        )
