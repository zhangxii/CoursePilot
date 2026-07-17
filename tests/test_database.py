import sqlite3
from pathlib import Path

import pytest

from coursepilot.database import connect_database, initialize_database


def test_initialize_database_is_idempotent_and_creates_required_schema(tmp_path: Path) -> None:
    database = tmp_path / "nested" / "coursepilot.db"

    initialize_database(database)
    initialize_database(database)

    with connect_database(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        migration_count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]

    assert {
        "teams",
        "team_members",
        "assignment",
        "courses",
        "materials",
        "answers",
        "reviews",
        "revisions",
        "schema_migrations",
    } <= tables
    assert foreign_keys == 1
    assert migration_count == 1


def test_database_rejects_second_team_and_second_assignment(tmp_path: Path) -> None:
    database = tmp_path / "coursepilot.db"
    initialize_database(database)

    with connect_database(database) as connection:
        connection.execute("INSERT INTO teams (id, name) VALUES ('main_team', 'CoursePilot')")
        connection.execute(
            """
            INSERT INTO assignment (id, team_id, title, requirements)
            VALUES ('main_assignment', 'main_team', '大作业', '完成系统设计')
            """
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO teams (id, name) VALUES ('other_team', '其他小组')")

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO assignment (id, team_id, title, requirements)
                VALUES ('other_assignment', 'main_team', '其他作业', '不应创建')
                """
            )


def test_answer_versions_are_unique_for_the_single_assignment(tmp_path: Path) -> None:
    database = tmp_path / "coursepilot.db"
    initialize_database(database)

    with connect_database(database) as connection:
        connection.execute("INSERT INTO teams (id, name) VALUES ('main_team', 'CoursePilot')")
        connection.execute(
            """
            INSERT INTO assignment (id, team_id, title, requirements)
            VALUES ('main_assignment', 'main_team', '大作业', '完成系统设计')
            """
        )
        connection.execute(
            """
            INSERT INTO answers (id, assignment_id, version, content)
            VALUES ('answer-1', 'main_assignment', 1, '初稿')
            """
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO answers (id, assignment_id, version, content)
                VALUES ('answer-2', 'main_assignment', 1, '重复版本')
                """
            )
