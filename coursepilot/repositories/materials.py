"""SQLite-backed material synchronization records."""

import sqlite3
from pathlib import Path
from uuid import uuid4

from coursepilot.database import connect_database
from coursepilot.models import (
    IndexStatus,
    MaterialMetadata,
    MaterialRecord,
    MaterialStatus,
    MaterialType,
)


class MaterialRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    def find_by_course_hash(self, course_id: str, file_hash: str) -> MaterialRecord | None:
        with connect_database(self._database_path) as connection:
            row = connection.execute(
                f"{_SELECT_MATERIAL} WHERE course_id = ? AND file_hash = ?",
                (course_id, file_hash),
            ).fetchone()
        return None if row is None else _to_model(row)

    def reserve(
        self, metadata: MaterialMetadata, *, file_name: str, file_hash: str
    ) -> MaterialRecord:
        material_id = str(uuid4())
        try:
            with connect_database(self._database_path) as connection:
                course = connection.execute(
                    "SELECT status FROM courses WHERE id = ?", (metadata.course_id,)
                ).fetchone()
                if course is None:
                    raise KeyError(metadata.course_id)
                connection.execute(
                    """
                    INSERT INTO materials (
                        id, course_id, file_name, file_hash, material_type, status, index_status
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        material_id,
                        metadata.course_id,
                        file_name,
                        file_hash,
                        metadata.material_type.value,
                        course[0],
                    ),
                )
        except sqlite3.IntegrityError:
            existing = self.find_by_course_hash(metadata.course_id, file_hash)
            if existing is None:
                raise
            return existing
        return self.get(material_id)

    def get(self, material_id: str) -> MaterialRecord:
        with connect_database(self._database_path) as connection:
            row = connection.execute(f"{_SELECT_MATERIAL} WHERE id = ?", (material_id,)).fetchone()
        if row is None:
            raise KeyError(material_id)
        return _to_model(row)

    def list_for_course(self, course_id: str) -> list[MaterialRecord]:
        with connect_database(self._database_path) as connection:
            rows = connection.execute(
                f"{_SELECT_MATERIAL} WHERE course_id = ? ORDER BY created_at, id",
                (course_id,),
            ).fetchall()
        return [_to_model(row) for row in rows]

    def mark_pending(self, material_id: str) -> MaterialRecord:
        return self._update_status(
            material_id, IndexStatus.PENDING, remote_file_id=None, error=None
        )

    def mark_uploaded(self, material_id: str, remote_file_id: str) -> MaterialRecord:
        return self._update_status(
            material_id,
            IndexStatus.UPLOADED,
            remote_file_id=remote_file_id,
            error=None,
        )

    def mark_indexed(self, material_id: str) -> MaterialRecord:
        current = self.get(material_id)
        return self._update_status(
            material_id,
            IndexStatus.INDEXED,
            remote_file_id=current.remote_file_id,
            error=None,
        )

    def mark_failed(
        self, material_id: str, error: str, *, remote_file_id: str | None = None
    ) -> MaterialRecord:
        if remote_file_id is None:
            remote_file_id = self.get(material_id).remote_file_id
        return self._update_status(
            material_id,
            IndexStatus.FAILED,
            remote_file_id=remote_file_id,
            error=error,
        )

    def _update_status(
        self,
        material_id: str,
        status: IndexStatus,
        *,
        remote_file_id: str | None,
        error: str | None,
    ) -> MaterialRecord:
        with connect_database(self._database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE materials
                SET index_status = ?, remote_file_id = ?, error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status.value, remote_file_id, error, material_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(material_id)
        return self.get(material_id)


_SELECT_MATERIAL = """
    SELECT id, course_id, file_name, file_hash, material_type, status,
           index_status, remote_file_id, error
    FROM materials
"""


def _to_model(
    row: tuple[str, str, str, str, str, str, str, str | None, str | None],
) -> MaterialRecord:
    return MaterialRecord(
        id=row[0],
        course_id=row[1],
        file_name=row[2],
        file_hash=row[3],
        material_type=MaterialType(row[4]),
        status=MaterialStatus(row[5]),
        index_status=IndexStatus(row[6]),
        remote_file_id=row[7],
        error=row[8],
    )
