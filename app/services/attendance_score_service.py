"""Attendance scoring (Phase 8.2) for one student in one course.

    attendance_score_100 = present_closed_sessions / closed_sessions * 100

Attendance is binary per CLOSED session (a record means present, no
record means absent); OPEN sessions never count. With zero CLOSED
sessions the score is None — never 0.

Eligibility limitation (explicitly accepted for now): every CLOSED
session in the course counts for every student. There is no
enrollment-start logic, so a student who joined late is counted absent
for sessions held before they joined.

score_100 is a full-precision Decimal — rounding is left to the
caller's response-building step (app.services.grade_normalization),
never fed back into further arithmetic. This module does not validate
that the student or course exist; callers do.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.repositories import attendance_score_repository as repo

_HUNDRED = Decimal(100)


@dataclass(frozen=True)
class AttendanceScore:
    closed_sessions: int
    present_sessions: int
    absent_sessions: int
    score_100: Decimal | None


def compute_attendance_score(closed_sessions: int, present_sessions: int) -> AttendanceScore:
    score_100 = (
        Decimal(present_sessions) / Decimal(closed_sessions) * _HUNDRED
        if closed_sessions > 0
        else None
    )
    return AttendanceScore(
        closed_sessions=closed_sessions,
        present_sessions=present_sessions,
        absent_sessions=closed_sessions - present_sessions,
        score_100=score_100,
    )


def get_attendance_score(db: Session, student_id: int, course_id: int) -> AttendanceScore:
    counts = repo.count_closed_and_present_sessions(db, student_id, course_id)
    return compute_attendance_score(counts.closed_sessions, counts.present_sessions)
