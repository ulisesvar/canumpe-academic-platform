"""The query behind the Phase 8.2 attendance score — academic.* only,
read-only, no calculation policy (that lives in
app.services.attendance_score_service).

Attendance is binary per CLOSED session: a record for the student
means present, no record means absent. OPEN sessions never count.
"""

from dataclasses import dataclass

from sqlalchemy import and_, distinct, func, select
from sqlalchemy.orm import Session

from app.academic.models import AttendanceRecord, AttendanceSession

CLOSED_STATUS = "CLOSED"


@dataclass(frozen=True)
class AttendanceCounts:
    closed_sessions: int
    present_sessions: int


def count_closed_and_present_sessions(
    db: Session, student_id: int, course_id: int
) -> AttendanceCounts:
    """One row, always. closed_sessions is every CLOSED session in the
    course; present_sessions is how many of them the student has a
    record for. Both are distinct-session counts, so a session can
    never be counted twice (uq_attendance_records_session_student
    already guarantees at most one record per session and student).
    Records for other students, other courses, or OPEN sessions never
    reach either count.
    """
    stmt = (
        select(
            func.count(distinct(AttendanceSession.id)).label("closed_sessions"),
            func.count(distinct(AttendanceRecord.attendance_session_id)).label("present_sessions"),
        )
        .select_from(AttendanceSession)
        .outerjoin(
            AttendanceRecord,
            and_(
                AttendanceRecord.attendance_session_id == AttendanceSession.id,
                AttendanceRecord.student_id == student_id,
            ),
        )
        .where(AttendanceSession.course_id == course_id, AttendanceSession.status == CLOSED_STATUS)
    )
    row = db.execute(stmt).one()
    return AttendanceCounts(
        closed_sessions=row.closed_sessions, present_sessions=row.present_sessions
    )
