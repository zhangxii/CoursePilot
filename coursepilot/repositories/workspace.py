"""Persistence for the singleton team, assignment, and shared work products."""

import json
from pathlib import Path
from uuid import uuid4

from coursepilot.database import connect_database
from coursepilot.models import (
    AnswerComparison,
    AnswerRecord,
    Assignment,
    MainAgentResult,
    NotesResult,
    ReviewRecord,
    ReviewResult,
    RevisionMode,
    RevisionRecord,
    Team,
    TeamMember,
)


class WorkspaceRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    def initialize_team(self, name: str, members: list[TeamMember]) -> Team:
        with connect_database(self._database_path) as db:
            if db.execute("SELECT 1 FROM teams").fetchone():
                raise ValueError("only one team is supported")
            db.execute("INSERT INTO teams (id,name) VALUES ('main_team',?)", (name,))
            db.executemany(
                "INSERT INTO team_members (id,team_id,name,role) VALUES (?,'main_team',?,?)",
                [(member.id, member.name, member.role) for member in members],
            )
        return self.get_team()

    def apply_agent_output(self, course_id: str, output: MainAgentResult, member_id: str) -> None:
        """Persist one agent result atomically across all affected business tables."""
        note_id, answer_id, review_id, revision_id = (str(uuid4()) for _ in range(4))
        with connect_database(self._database_path) as db:
            if output.notes_output is not None:
                db.execute(
                    "INSERT INTO course_notes (id,course_id,result_json) VALUES (?,?,?)",
                    (note_id, course_id, output.notes_output.model_dump_json()),
                )
            latest = db.execute(
                "SELECT id,version FROM answers ORDER BY version DESC LIMIT 1"
            ).fetchone()
            if output.assignment_output is not None:
                version = 1 if latest is None else latest[1] + 1
                db.execute(
                    "INSERT INTO answers (id,assignment_id,version,content,operated_by_member_id) "
                    "VALUES (?,'main_assignment',?,?,?)",
                    (answer_id, version, output.assignment_output.shared_answer, member_id),
                )
                latest = (answer_id, version)
            if output.review_output is not None:
                if latest is None:
                    raise ValueError("review requires a shared answer")
                db.execute(
                    "INSERT INTO reviews (id,answer_id,result_json,total_score) VALUES (?,?,?,?)",
                    (
                        review_id,
                        latest[0],
                        output.review_output.model_dump_json(),
                        output.review_output.total_score,
                    ),
                )
            if output.revision_output is not None:
                if latest is None:
                    raise ValueError("revision requires a shared answer")
                review_row = db.execute(
                    "SELECT id FROM reviews WHERE answer_id=? "
                    "ORDER BY created_at DESC,id DESC LIMIT 1",
                    (latest[0],),
                ).fetchone()
                if review_row is None:
                    raise ValueError("revision requires a review for the current answer")
                result_answer_id = str(uuid4())
                db.execute(
                    "INSERT INTO answers (id,assignment_id,version,content,operated_by_member_id) "
                    "VALUES (?,'main_assignment',?,?,?)",
                    (
                        result_answer_id,
                        latest[1] + 1,
                        output.revision_output.revised_answer,
                        member_id,
                    ),
                )
                db.execute(
                    "INSERT INTO revisions (id,source_answer_id,review_id,result_answer_id,mode,"
                    "change_summary,operated_by_member_id,unresolved_issues_json) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        revision_id,
                        latest[0],
                        review_row[0],
                        result_answer_id,
                        output.revision_output.mode.value,
                        "；".join(output.revision_output.changes),
                        member_id,
                        json.dumps(output.revision_output.unresolved_issues, ensure_ascii=False),
                    ),
                )

    def save_notes(self, course_id: str, result: NotesResult) -> str:
        note_id = str(uuid4())
        with connect_database(self._database_path) as db:
            db.execute(
                "INSERT INTO course_notes (id,course_id,result_json) VALUES (?,?,?)",
                (note_id, course_id, result.model_dump_json()),
            )
        return note_id

    def get_notes(self, note_id: str) -> NotesResult:
        with connect_database(self._database_path) as db:
            row = db.execute(
                "SELECT result_json FROM course_notes WHERE id=?", (note_id,)
            ).fetchone()
        if row is None:
            raise KeyError(note_id)
        return NotesResult.model_validate(json.loads(row[0]))

    def get_team(self) -> Team:
        with connect_database(self._database_path) as db:
            team = db.execute("SELECT name FROM teams WHERE id='main_team'").fetchone()
            members = db.execute(
                "SELECT id,name,role FROM team_members WHERE team_id='main_team' ORDER BY id"
            ).fetchall()
        if team is None:
            raise KeyError("main_team")
        return Team(
            name=team[0],
            members=[TeamMember(id=row[0], name=row[1], role=row[2]) for row in members],
        )

    def initialize_assignment(
        self, title: str, requirements: str, rubric: str | None
    ) -> Assignment:
        with connect_database(self._database_path) as db:
            if db.execute("SELECT 1 FROM assignment").fetchone():
                raise ValueError("only one assignment is supported")
            db.execute(
                "INSERT INTO assignment (id,team_id,title,requirements,rubric) "
                "VALUES ('main_assignment','main_team',?,?,?)",
                (title, requirements, rubric),
            )
        return self.get_assignment()

    def get_assignment(self) -> Assignment:
        with connect_database(self._database_path) as db:
            row = db.execute(
                "SELECT title,requirements,rubric FROM assignment WHERE id='main_assignment'"
            ).fetchone()
        if row is None:
            raise KeyError("main_assignment")
        return Assignment(title=row[0], requirements=row[1], rubric=row[2])

    def update_assignment(self, title: str, requirements: str, rubric: str | None) -> Assignment:
        with connect_database(self._database_path) as db:
            cursor = db.execute(
                "UPDATE assignment SET title=?,requirements=?,rubric=?,"
                "updated_at=CURRENT_TIMESTAMP "
                "WHERE id='main_assignment'",
                (title, requirements, rubric),
            )
            if cursor.rowcount != 1:
                raise KeyError("main_assignment")
        return self.get_assignment()

    def add_answer(self, content: str, member_id: str) -> AnswerRecord:
        answer_id = str(uuid4())
        with connect_database(self._database_path) as db:
            version = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM answers "
                "WHERE assignment_id='main_assignment'"
            ).fetchone()[0]
            db.execute(
                "INSERT INTO answers (id,assignment_id,version,content,operated_by_member_id) "
                "VALUES (?,'main_assignment',?,?,?)",
                (answer_id, version, content, member_id),
            )
        return self.get_answer(answer_id)

    def get_answer(self, answer_id: str) -> AnswerRecord:
        with connect_database(self._database_path) as db:
            row = db.execute(
                "SELECT id,version,content,operated_by_member_id FROM answers WHERE id=?",
                (answer_id,),
            ).fetchone()
        if row is None:
            raise KeyError(answer_id)
        return AnswerRecord(id=row[0], version=row[1], content=row[2], operated_by_member_id=row[3])

    def latest_answer(self) -> AnswerRecord | None:
        with connect_database(self._database_path) as db:
            row = db.execute("SELECT id FROM answers ORDER BY version DESC LIMIT 1").fetchone()
        return None if row is None else self.get_answer(row[0])

    def add_review(self, answer_id: str, result: ReviewResult) -> ReviewRecord:
        review_id = str(uuid4())
        with connect_database(self._database_path) as db:
            db.execute(
                "INSERT INTO reviews (id,answer_id,result_json,total_score) VALUES (?,?,?,?)",
                (review_id, answer_id, result.model_dump_json(), result.total_score),
            )
        return ReviewRecord(id=review_id, answer_id=answer_id, result=result)

    def latest_review(self, answer_id: str) -> ReviewRecord | None:
        with connect_database(self._database_path) as db:
            row = db.execute(
                "SELECT id,result_json FROM reviews WHERE answer_id=? "
                "ORDER BY created_at DESC,id DESC LIMIT 1",
                (answer_id,),
            ).fetchone()
        if row is None:
            return None
        return ReviewRecord(
            id=row[0], answer_id=answer_id, result=ReviewResult.model_validate(json.loads(row[1]))
        )

    def revise(
        self,
        source: AnswerRecord,
        review: ReviewRecord,
        content: str,
        member_id: str,
        mode: RevisionMode,
        summary: str,
        unresolved_issues: list[str] | None = None,
    ) -> tuple[AnswerRecord, RevisionRecord]:
        answer_id, revision_id = str(uuid4()), str(uuid4())
        revision = RevisionRecord(
            id=revision_id,
            source_answer_id=source.id,
            review_id=review.id,
            result_answer_id=answer_id,
            mode=mode,
            change_summary=summary,
            unresolved_issues=unresolved_issues or [],
        )
        with connect_database(self._database_path) as db:
            db.execute(
                "INSERT INTO answers (id,assignment_id,version,content,operated_by_member_id) "
                "VALUES (?,'main_assignment',?,?,?)",
                (answer_id, source.version + 1, content, member_id),
            )
            db.execute(
                "INSERT INTO revisions (id,source_answer_id,review_id,result_answer_id,mode,"
                "change_summary,operated_by_member_id,unresolved_issues_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    revision_id,
                    source.id,
                    review.id,
                    answer_id,
                    mode.value,
                    summary,
                    member_id,
                    json.dumps(unresolved_issues or [], ensure_ascii=False),
                ),
            )
        return self.get_answer(answer_id), revision

    def compare_revision(self, revision: RevisionRecord) -> AnswerComparison:
        source = self.get_answer(revision.source_answer_id)
        result = self.get_answer(revision.result_answer_id)
        review = self.latest_review(source.id)
        critical = [] if review is None else review.result.critical_issues
        unresolved = [issue for issue in critical if issue in revision.unresolved_issues]
        return AnswerComparison(
            source_version=source.version,
            result_version=result.version,
            operated_by_member_id=result.operated_by_member_id,
            change_summary=revision.change_summary,
            resolved_issues=[issue for issue in critical if issue not in unresolved],
            unresolved_issues=unresolved,
        )

    def latest_revision(self) -> RevisionRecord | None:
        with connect_database(self._database_path) as db:
            row = db.execute(
                "SELECT id,source_answer_id,review_id,result_answer_id,mode,change_summary,"
                "unresolved_issues_json "
                "FROM revisions ORDER BY created_at DESC,id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return RevisionRecord(
            id=row[0],
            source_answer_id=row[1],
            review_id=row[2],
            result_answer_id=row[3],
            mode=RevisionMode(row[4]),
            change_summary=row[5],
            unresolved_issues=json.loads(row[6]),
        )
