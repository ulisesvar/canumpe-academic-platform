"""Builds staging.attendance_* from one batch's extracted rows.

Staging is fully rebuilt for this source_system on every run. Only
structurally well-formed rows are written; anything else is reported as
an issue and left out of staging. This function does not decide whether
the batch as a whole may proceed to merge — that is
`validate_staged_batch`'s job, reading staging back.
"""

import uuid

from sqlalchemy import delete, insert
from sqlalchemy.engine import Connection

from app.integration.attendance.hashing import (
    attendance_record_hash,
    attendance_session_hash,
    attendance_student_hash,
)
from app.integration.attendance.models.staging import (
    StagingAttendanceRecord,
    StagingAttendanceSession,
    StagingAttendanceStudent,
)
from app.integration.attendance.source import AttendanceExtractionResult

SOURCE_SYSTEM = "attendance"

_VALID_STATUSES = {"OPEN", "CLOSED"}


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def write_staging_batch(
    connection: Connection, batch_id: uuid.UUID, extraction: AttendanceExtractionResult
) -> list[str]:
    issues: list[str] = []

    connection.execute(
        delete(StagingAttendanceStudent).where(
            StagingAttendanceStudent.source_system == SOURCE_SYSTEM
        )
    )
    connection.execute(
        delete(StagingAttendanceSession).where(
            StagingAttendanceSession.source_system == SOURCE_SYSTEM
        )
    )
    connection.execute(
        delete(StagingAttendanceRecord).where(
            StagingAttendanceRecord.source_system == SOURCE_SYSTEM
        )
    )

    student_rows = []
    for s in extraction.students:
        account_number = _clean_text(s.account_number)
        if not account_number:
            issues.append(f"attendance student source_id={s.source_id!r} is missing account_number")
            continue
        student_rows.append(
            {
                "batch_id": batch_id,
                "source_system": SOURCE_SYSTEM,
                "source_id": s.source_id,
                "account_number": account_number,
                "source_hash": attendance_student_hash(s.account_number),
            }
        )
    if student_rows:
        connection.execute(insert(StagingAttendanceStudent), student_rows)

    session_rows = []
    for sess in extraction.sessions:
        if sess.opened_at is None:
            issues.append(f"attendance session source_id={sess.source_id!r} is missing opened_at")
            continue
        if sess.status not in _VALID_STATUSES:
            issues.append(
                f"attendance session source_id={sess.source_id!r} has invalid "
                f"status {sess.status!r}"
            )
            continue
        session_rows.append(
            {
                "batch_id": batch_id,
                "source_system": SOURCE_SYSTEM,
                "source_id": sess.source_id,
                "opened_at": sess.opened_at,
                "closed_at": sess.closed_at,
                "status": sess.status,
                "source_hash": attendance_session_hash(
                    sess.opened_at, sess.closed_at, sess.status
                ),
            }
        )
    if session_rows:
        connection.execute(insert(StagingAttendanceSession), session_rows)

    record_rows = [
        {
            "batch_id": batch_id,
            "source_system": SOURCE_SYSTEM,
            "source_id": a.source_id,
            "student_source_id": a.student_source_id,
            "session_source_id": a.session_source_id,
            "recorded_at": a.recorded_at,
            "source_hash": attendance_record_hash(
                a.student_source_id, a.session_source_id, a.recorded_at
            ),
        }
        for a in extraction.attendances
    ]
    if record_rows:
        connection.execute(insert(StagingAttendanceRecord), record_rows)

    return issues
