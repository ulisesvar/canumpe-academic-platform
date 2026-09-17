"""A minimal fake Attendance PostgreSQL schema for tests.

Mimics only the columns app.integration.attendance.source actually
queries — never telegram_id/telegram_username/latitude/longitude/
distance_meters, and never a connection to a real Attendance instance.
Lives in the "public" schema of the same test database, using the real
source table names (students, attendance_sessions, attendances) since
nothing else in this project uses those bare, unqualified names.
"""

from datetime import datetime

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS students (
    id SERIAL PRIMARY KEY,
    account_number TEXT NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS attendance_sessions (
    id SERIAL PRIMARY KEY,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'OPEN'
);
CREATE TABLE IF NOT EXISTS attendances (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    latitude DOUBLE PRECISION NOT NULL DEFAULT 0,
    longitude DOUBLE PRECISION NOT NULL DEFAULT 0,
    distance_meters DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

FAKE_ATTENDANCE_TABLES = ("attendances", "attendance_sessions", "students")

PIPELINE_TABLES = (
    "integration.attendance_record_sources",
    "integration.attendance_session_sources",
    "integration.student_sources",
    "integration.course_sources",
    "integration.sync_runs",
    "integration.sync_state",
    "integration.sync_issues",
    "academic.attendance_records",
    "academic.attendance_sessions",
    "academic.students",
    "academic.courses",
    "raw_attendance.attendances",
    "raw_attendance.sessions",
    "raw_attendance.students",
    "staging.attendance_records",
    "staging.attendance_sessions",
    "staging.attendance_students",
)


def create_fake_attendance_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(CREATE_TABLES_SQL))


def truncate_fake_attendance_schema(engine: Engine) -> None:
    tables = ", ".join(FAKE_ATTENDANCE_TABLES)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


def truncate_attendance_pipeline_tables(engine: Engine) -> None:
    tables = ", ".join(PIPELINE_TABLES)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


def insert_student(
    connection: Connection, *, account_number: str, registered_at: datetime | None = None
) -> int:
    return connection.execute(
        text(
            "INSERT INTO students (account_number, registered_at) "
            "VALUES (:account_number, COALESCE(:registered_at, now())) RETURNING id"
        ),
        {"account_number": account_number, "registered_at": registered_at},
    ).scalar_one()


def insert_session(
    connection: Connection,
    *,
    status: str = "OPEN",
    opened_at: datetime | None = None,
    closed_at: datetime | None = None,
) -> int:
    return connection.execute(
        text(
            "INSERT INTO attendance_sessions (opened_at, closed_at, status) "
            "VALUES (COALESCE(:opened_at, now()), :closed_at, :status) RETURNING id"
        ),
        {"opened_at": opened_at, "closed_at": closed_at, "status": status},
    ).scalar_one()


def insert_attendance(
    connection: Connection,
    *,
    session_id: int,
    student_id: int,
    created_at: datetime | None = None,
    latitude: float = 19.4326,
    longitude: float = -99.1332,
    distance_meters: float = 12.5,
) -> int:
    """latitude/longitude/distance_meters mirror the real source schema
    (NOT NULL columns) so extraction can be proven to ignore them, not
    just happen to have nothing to ignore.
    """
    return connection.execute(
        text(
            "INSERT INTO attendances "
            "(session_id, student_id, latitude, longitude, distance_meters, created_at) "
            "VALUES (:session_id, :student_id, :latitude, :longitude, :distance_meters, "
            "COALESCE(:created_at, now())) RETURNING id"
        ),
        {
            "session_id": session_id,
            "student_id": student_id,
            "latitude": latitude,
            "longitude": longitude,
            "distance_meters": distance_meters,
            "created_at": created_at,
        },
    ).scalar_one()


def update_session_status(connection: Connection, session_id: int, status: str) -> None:
    connection.execute(
        text("UPDATE attendance_sessions SET status = :status WHERE id = :id"),
        {"status": status, "id": session_id},
    )
