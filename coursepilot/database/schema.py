"""SQLite connection and idempotent schema initialization."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 5

INITIAL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY CHECK (id = 'main_team'),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS team_members (
    id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL DEFAULT 'main_team' CHECK (team_id = 'main_team'),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    role TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS assignment (
    id TEXT PRIMARY KEY CHECK (id = 'main_assignment'),
    team_id TEXT NOT NULL UNIQUE DEFAULT 'main_team' CHECK (team_id = 'main_team'),
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    requirements TEXT NOT NULL CHECK (length(trim(requirements)) > 0),
    rubric TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS courses (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    course_date TEXT NOT NULL,
    teacher TEXT NOT NULL CHECK (length(trim(teacher)) > 0),
    topic TEXT NOT NULL CHECK (length(trim(topic)) > 0),
    status TEXT NOT NULL CHECK (status IN ('current', 'archived')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL,
    file_name TEXT NOT NULL CHECK (length(trim(file_name)) > 0),
    file_hash TEXT NOT NULL,
    material_type TEXT NOT NULL CHECK (
        material_type IN ('pdf', 'pptx')
    ),
    status TEXT NOT NULL CHECK (status IN ('current', 'archived')),
    index_status TEXT NOT NULL DEFAULT 'pending' CHECK (
        index_status IN ('pending', 'indexed', 'failed')
    ),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
    UNIQUE (course_id, file_hash)
);

CREATE TABLE IF NOT EXISTS answers (
    id TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL DEFAULT 'main_assignment' CHECK (
        assignment_id = 'main_assignment'
    ),
    version INTEGER NOT NULL CHECK (version >= 1),
    content TEXT NOT NULL CHECK (length(trim(content)) > 0),
    operated_by_member_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (assignment_id) REFERENCES assignment(id) ON DELETE CASCADE,
    FOREIGN KEY (operated_by_member_id) REFERENCES team_members(id) ON DELETE RESTRICT,
    UNIQUE (assignment_id, version)
);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    answer_id TEXT NOT NULL,
    result_json TEXT NOT NULL CHECK (json_valid(result_json)),
    total_score INTEGER NOT NULL CHECK (total_score BETWEEN 0 AND 100),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (answer_id) REFERENCES answers(id) ON DELETE CASCADE,
    UNIQUE (id, answer_id)
);

CREATE TABLE IF NOT EXISTS revisions (
    id TEXT PRIMARY KEY,
    source_answer_id TEXT NOT NULL,
    review_id TEXT NOT NULL,
    result_answer_id TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL CHECK (mode IN ('conservative', 'deep_restructure')),
    change_summary TEXT NOT NULL CHECK (length(trim(change_summary)) > 0),
    operated_by_member_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (review_id, source_answer_id) REFERENCES reviews(id, answer_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (result_answer_id) REFERENCES answers(id) ON DELETE RESTRICT,
    FOREIGN KEY (operated_by_member_id) REFERENCES team_members(id) ON DELETE RESTRICT
);

CREATE TRIGGER IF NOT EXISTS validate_revision_version
BEFORE INSERT ON revisions
FOR EACH ROW
WHEN (
    SELECT version FROM answers WHERE id = NEW.result_answer_id
) != (
    SELECT version + 1 FROM answers WHERE id = NEW.source_answer_id
)
BEGIN
    SELECT RAISE(ABORT, 'result answer must be next answer version');
END;

CREATE INDEX IF NOT EXISTS idx_materials_course_status
    ON materials(course_id, status);
CREATE INDEX IF NOT EXISTS idx_answers_assignment_version
    ON answers(assignment_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_reviews_answer
    ON reviews(answer_id);
CREATE INDEX IF NOT EXISTS idx_revisions_source
    ON revisions(source_answer_id);
"""

MIGRATIONS = {
    1: INITIAL_SCHEMA_SQL,
    2: """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_courses_single_current
            ON courses(status) WHERE status = 'current';
    """,
    3: """
        CREATE TABLE IF NOT EXISTS course_notes (
            id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            result_json TEXT NOT NULL CHECK (json_valid(result_json)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
        );
    """,
    4: """
        ALTER TABLE revisions ADD COLUMN unresolved_issues_json TEXT NOT NULL DEFAULT '[]'
            CHECK (json_valid(unresolved_issues_json));
    """,
    5: """
        DROP INDEX IF EXISTS idx_materials_course_status;
        ALTER TABLE materials RENAME TO materials_legacy;
        CREATE TABLE materials (
            id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            file_name TEXT NOT NULL CHECK (length(trim(file_name)) > 0),
            file_hash TEXT NOT NULL,
            material_type TEXT NOT NULL CHECK (material_type IN ('pdf', 'pptx')),
            status TEXT NOT NULL CHECK (status IN ('current', 'archived')),
            index_status TEXT NOT NULL DEFAULT 'pending' CHECK (
                index_status IN ('pending', 'indexed', 'failed')
            ),
            content_markdown TEXT NOT NULL DEFAULT '',
            error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
            UNIQUE (course_id, file_hash)
        );
        INSERT INTO materials (
            id, course_id, file_name, file_hash, material_type, status,
            index_status, error, created_at, updated_at
        )
        SELECT id, course_id, file_name, file_hash, material_type, status,
               CASE WHEN index_status = 'failed' THEN 'failed'
                    ELSE 'pending' END,
               error, created_at, updated_at
        FROM materials_legacy;
        DROP TABLE materials_legacy;
        CREATE INDEX idx_materials_course_status ON materials(course_id, status);
    """,
}


@contextmanager
def connect_database(path: str | Path) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection with integrity constraints enabled."""

    connection = sqlite3.connect(Path(path))
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(path: str | Path) -> Path:
    """Create or migrate the business database and return its resolved path."""

    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with connect_database(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied_versions = {
            row[0] for row in connection.execute("SELECT version FROM schema_migrations")
        }
        for version in range(1, SCHEMA_VERSION + 1):
            if version in applied_versions:
                continue
            connection.executescript(MIGRATIONS[version])
            connection.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))

    return database_path.resolve()
