"""Explicit, read-only queries backing the Phase 5 student read API.

Every query here selects exactly the columns a route needs — no ORM
relationship traversal, no lazy loading, no N+1 risk, and no access to
integration.*/raw_moodle.*/raw_attendance.*/staging.*. This module never
writes to the database.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.academic.models import (
    AttendanceRecord,
    AttendanceSession,
    Course,
    Enrollment,
    GradeItem,
    Student,
    StudentGrade,
)


def student_exists(db: Session, student_id: int) -> bool:
    return (
        db.execute(select(Student.id).where(Student.id == student_id)).scalar_one_or_none()
        is not None
    )


def get_student_identity(db: Session, student_id: int) -> RowMapping | None:
    """Minimal identity fields for GET /me — never anything beyond what
    that response needs (no name, no email, no source mappings).
    """
    stmt = select(Student.id, Student.account_number).where(Student.id == student_id)
    return db.execute(stmt).mappings().one_or_none()


def list_enrolled_courses(db: Session, student_id: int) -> Sequence[RowMapping]:
    """One row per course the student is enrolled in, ordered by
    canonical course id for deterministic responses.
    """
    stmt = (
        select(Course.id, Course.name, Course.active)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .where(Enrollment.student_id == student_id)
        .order_by(Course.id)
    )
    return db.execute(stmt).mappings().all()


def list_attendance_records(db: Session, student_id: int) -> Sequence[RowMapping]:
    """One row per attendance record the student has — a recorded
    presence event, never an inferred absence. Ordered chronologically
    by the session's opened_at, with the session id as a tiebreaker for
    determinism if two sessions share a timestamp.
    """
    stmt = (
        select(
            AttendanceSession.course_id,
            AttendanceRecord.attendance_session_id,
            AttendanceSession.opened_at,
        )
        .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.attendance_session_id)
        .where(AttendanceRecord.student_id == student_id)
        .order_by(AttendanceSession.opened_at, AttendanceSession.id)
    )
    return db.execute(stmt).mappings().all()


def list_student_grades(db: Session, student_id: int) -> Sequence[RowMapping]:
    """One row per grade item the student has a canonical grade row
    for — grade stays whatever academic.student_grades.grade holds
    (nullable), never coerced here. Ordered by grade item id for
    deterministic responses.
    """
    stmt = (
        select(
            GradeItem.course_id,
            GradeItem.id,
            GradeItem.name,
            GradeItem.activity_type,
            GradeItem.max_grade,
            StudentGrade.grade,
        )
        .join(StudentGrade, StudentGrade.grade_item_id == GradeItem.id)
        .where(StudentGrade.student_id == student_id)
        .order_by(GradeItem.id)
    )
    return db.execute(stmt).mappings().all()
