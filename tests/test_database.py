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
            "INSERT INTO team_members (id, team_id, name) "
            "VALUES ('member-1', 'main_team', '张同学')"
        )
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
            "INSERT INTO team_members (id, team_id, name) "
            "VALUES ('member-1', 'main_team', '张同学')"
        )
        connection.execute(
            """
            INSERT INTO assignment (id, team_id, title, requirements)
            VALUES ('main_assignment', 'main_team', '大作业', '完成系统设计')
            """
        )
        connection.execute(
            """
            INSERT INTO answers (
                id, assignment_id, version, content, operated_by_member_id
            ) VALUES ('answer-1', 'main_assignment', 1, '初稿', 'member-1')
            """
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO answers (
                    id, assignment_id, version, content, operated_by_member_id
                ) VALUES ('answer-2', 'main_assignment', 1, '重复版本', 'member-1')
                """
            )


def test_revision_requires_an_operator_and_review_of_its_source_answer(tmp_path: Path) -> None:
    database = tmp_path / "coursepilot.db"
    initialize_database(database)

    with connect_database(database) as connection:
        connection.execute("INSERT INTO teams (id, name) VALUES ('main_team', 'CoursePilot')")
        connection.execute(
            "INSERT INTO team_members (id, team_id, name) "
            "VALUES ('member-1', 'main_team', '张同学')"
        )
        connection.execute(
            """
            INSERT INTO assignment (id, team_id, title, requirements)
            VALUES ('main_assignment', 'main_team', '大作业', '完成系统设计')
            """
        )
        for answer_id, version in (("answer-1", 1), ("answer-2", 2), ("answer-3", 3)):
            connection.execute(
                """
                INSERT INTO answers (
                    id, assignment_id, version, content, operated_by_member_id
                ) VALUES (?, 'main_assignment', ?, '答案', 'member-1')
                """,
                (answer_id, version),
            )
        connection.execute(
            """
            INSERT INTO reviews (id, answer_id, result_json, total_score)
            VALUES ('review-1', 'answer-1', '{}', 80)
            """
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO revisions (
                    id, source_answer_id, review_id, result_answer_id, mode,
                    change_summary, operated_by_member_id
                ) VALUES (
                    'revision-wrong-review', 'answer-2', 'review-1', 'answer-3',
                    'conservative', '修改', 'member-1'
                )
                """
            )


def test_revision_result_must_be_the_next_answer_version(tmp_path: Path) -> None:
    database = tmp_path / "coursepilot.db"
    initialize_database(database)

    with connect_database(database) as connection:
        connection.execute("INSERT INTO teams (id, name) VALUES ('main_team', 'CoursePilot')")
        connection.execute(
            "INSERT INTO team_members (id, team_id, name) "
            "VALUES ('member-1', 'main_team', '张同学')"
        )
        connection.execute(
            """
            INSERT INTO assignment (id, team_id, title, requirements)
            VALUES ('main_assignment', 'main_team', '大作业', '完成系统设计')
            """
        )
        for answer_id, version in (("answer-1", 1), ("answer-2", 2), ("answer-3", 3)):
            connection.execute(
                """
                INSERT INTO answers (
                    id, assignment_id, version, content, operated_by_member_id
                ) VALUES (?, 'main_assignment', ?, '答案', 'member-1')
                """,
                (answer_id, version),
            )
        connection.execute(
            """
            INSERT INTO reviews (id, answer_id, result_json, total_score)
            VALUES ('review-1', 'answer-1', '{}', 80)
            """
        )

        with pytest.raises(sqlite3.IntegrityError, match="next answer version"):
            connection.execute(
                """
                INSERT INTO revisions (
                    id, source_answer_id, review_id, result_answer_id, mode,
                    change_summary, operated_by_member_id
                ) VALUES (
                    'revision-skip-version', 'answer-1', 'review-1', 'answer-3',
                    'conservative', '跨级修改', 'member-1'
                )
                """
            )

        connection.execute(
            """
            INSERT INTO revisions (
                id, source_answer_id, review_id, result_answer_id, mode,
                change_summary, operated_by_member_id
            ) VALUES (
                'revision-valid', 'answer-1', 'review-1', 'answer-2',
                'conservative', '正常修改', 'member-1'
            )
            """
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO revisions (
                    id, source_answer_id, review_id, result_answer_id, mode, change_summary
                ) VALUES (
                    'revision-no-member', 'answer-1', 'review-1', 'answer-2',
                    'conservative', '修改'
                )
                """
            )
