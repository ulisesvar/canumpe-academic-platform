"""Writes one batch's extracted rows into raw_attendance.* — a faithful,
append-only landing copy. RAW is never validated and never truncated by
a sync run.
"""

import uuid

from sqlalchemy import insert
from sqlalchemy.engine import Connection

from app.integration.attendance.hashing import (
    attendance_record_hash,
    attendance_session_hash,
    attendance_student_hash,
)
from app.integration.attendance.models.raw import (
    RawAttendanceRecord,
    RawAttendanceSession,
    RawAttendanceStudent,
)
from app.integration.attendance.source import AttendanceExtractionResult


def write_raw_batch(
    connection: Connection, batch_id: uuid.UUID, extraction: AttendanceExtractionResult
) -> None:
    if extraction.students:
        connection.execute(
            insert(RawAttendanceStudent),
            [
                {
                    "batch_id": batch_id,
                    "source_id": s.source_id,
                    "account_number": s.account_number,
                    "registered_at": s.registered_at,
                    "source_hash": attendance_student_hash(s.account_number),
                }
                for s in extraction.students
            ],
        )

    if extraction.sessions:
        connection.execute(
            insert(RawAttendanceSession),
            [
                {
                    "batch_id": batch_id,
                    "source_id": sess.source_id,
                    "opened_at": sess.opened_at,
                    "closed_at": sess.closed_at,
                    "status": sess.status,
                    "source_hash": attendance_session_hash(
                        sess.opened_at, sess.closed_at, sess.status
                    ),
                }
                for sess in extraction.sessions
            ],
        )

    if extraction.attendances:
        connection.execute(
            insert(RawAttendanceRecord),
            [
                {
                    "batch_id": batch_id,
                    "source_id": a.source_id,
                    "student_source_id": a.student_source_id,
                    "session_source_id": a.session_source_id,
                    "recorded_at": a.recorded_at,
                    "source_hash": attendance_record_hash(
                        a.student_source_id, a.session_source_id, a.recorded_at
                    ),
                }
                for a in extraction.attendances
            ],
        )
