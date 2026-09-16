"""Read-only extraction from the Attendance PostgreSQL database.

Queries only. No writes, no schema changes, no assumption that the
source grants anything beyond SELECT. All entity queries run inside one
REPEATABLE READ, READ ONLY transaction so that students/sessions/
attendances extracted for a batch represent one coherent source
snapshot.

Only the columns actually needed for academic attendance are selected —
never latitude/longitude/distance_meters/telegram_username. See the
README's minimal-data principle.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from app.integration.attendance.errors import AttendanceSourceIntegrityError


@dataclass(frozen=True)
class ExtractedAttendanceStudent:
    source_id: str
    account_number: str
    registered_at: datetime | None


@dataclass(frozen=True)
class ExtractedAttendanceSession:
    source_id: str
    opened_at: datetime
    closed_at: datetime | None
    status: str


@dataclass(frozen=True)
class ExtractedAttendanceRecord:
    source_id: str
    student_source_id: str
    session_source_id: str
    recorded_at: datetime


@dataclass(frozen=True)
class AttendanceExtractionResult:
    snapshot_time: datetime
    students: Sequence[ExtractedAttendanceStudent]
    sessions: Sequence[ExtractedAttendanceSession]
    attendances: Sequence[ExtractedAttendanceRecord]


def _fetch_students(connection: Connection) -> list[ExtractedAttendanceStudent]:
    rows = connection.execute(
        text("SELECT id, account_number, registered_at FROM students")
    ).all()

    by_account: dict[str, set[str]] = {}
    for row in rows:
        by_account.setdefault(row.account_number, set()).add(str(row.id))
    duplicates = {account: ids for account, ids in by_account.items() if len(ids) > 1}
    if duplicates:
        details = "; ".join(
            f"account_number={account!r} -> attendance student ids {sorted(ids)}"
            for account, ids in sorted(duplicates.items())
        )
        raise AttendanceSourceIntegrityError(
            f"duplicate account_number maps to multiple Attendance students: {details}"
        )

    return [
        ExtractedAttendanceStudent(
            source_id=str(row.id),
            account_number=row.account_number,
            registered_at=row.registered_at,
        )
        for row in rows
    ]


def _fetch_sessions(connection: Connection) -> list[ExtractedAttendanceSession]:
    rows = connection.execute(
        text("SELECT id, opened_at, closed_at, status FROM attendance_sessions")
    ).all()
    return [
        ExtractedAttendanceSession(
            source_id=str(row.id),
            opened_at=row.opened_at,
            closed_at=row.closed_at,
            status=row.status,
        )
        for row in rows
    ]


def _fetch_attendances(connection: Connection) -> list[ExtractedAttendanceRecord]:
    rows = connection.execute(
        text("SELECT id, session_id, student_id, created_at FROM attendances")
    ).all()
    return [
        ExtractedAttendanceRecord(
            source_id=str(row.id),
            student_source_id=str(row.student_id),
            session_source_id=str(row.session_id),
            recorded_at=row.created_at,
        )
        for row in rows
    ]


def extract_attendance_batch(attendance_engine: Engine) -> AttendanceExtractionResult:
    """Extract all students/sessions/attendances from the Attendance DB.

    Phase 3 uses a full extraction of the whole source (current volume is
    tiny — 13 students, 7 sessions, 66 attendances — so no incremental
    watermark yet). Runs inside a single REPEATABLE READ, READ ONLY
    transaction, always committed (read-only, so this just releases the
    snapshot) or rolled back on error, with the connection always closed.
    """
    with attendance_engine.connect() as connection, connection.begin():
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        snapshot_time = connection.execute(text("SELECT now()")).scalar_one()

        students = _fetch_students(connection)
        sessions = _fetch_sessions(connection)
        attendances = _fetch_attendances(connection)

    return AttendanceExtractionResult(
        snapshot_time=snapshot_time, students=students, sessions=sessions, attendances=attendances
    )
