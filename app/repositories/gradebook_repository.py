"""Bulk, read-only queries backing the Phase 8.4 course roster and
gradebook — academic.* only. Each function answers one question for the
WHOLE course in a single statement, so the gradebook's query count does
not grow with class size. No calculation policy lives here (that is
app.services.evaluation_service / attendance_score_service /
participation_service, reused by app.services.gradebook_service).
"""

from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import distinct, func, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.academic.models import (
    AttendanceRecord,
    AttendanceSession,
    Enrollment,
    GradeItem,
    GradeItemEvaluation,
    ParticipationObservation,
    Student,
    StudentGrade,
)
from app.repositories.attendance_score_repository import CLOSED_STATUS


def list_roster(db: Session, course_id: int) -> Sequence[RowMapping]:
    """The course's students, ordered by last name, first name, then id.

    Follows the canonical enrollment data as it exists: enrollments with
    active=true. NOTE: ingestion currently never sets active=false — a
    student who vanishes from Moodle's enrolments stays active here — so
    this filter does not yet hide anyone.
    """
    stmt = (
        select(
            Student.id.label("student_id"),
            Student.account_number,
            Student.first_name,
            Student.last_name,
        )
        .join(Enrollment, Enrollment.student_id == Student.id)
        .where(Enrollment.course_id == course_id, Enrollment.active.is_(True))
        .order_by(Student.last_name, Student.first_name, Student.id)
    )
    return db.execute(stmt).mappings().all()


def list_course_grade_items(db: Session, course_id: int) -> Sequence[RowMapping]:
    """Every grade item in the course, ordered by id, left-joined to its
    evaluation assignment (category_id / counts_toward_current_grade are
    None for an unassigned item).
    """
    stmt = (
        select(
            GradeItem.id.label("grade_item_id"),
            GradeItem.name,
            GradeItem.activity_type,
            GradeItem.max_grade,
            GradeItemEvaluation.category_id,
            GradeItemEvaluation.counts_toward_current_grade,
        )
        .outerjoin(GradeItemEvaluation, GradeItemEvaluation.grade_item_id == GradeItem.id)
        .where(GradeItem.course_id == course_id)
        .order_by(GradeItem.id)
    )
    return db.execute(stmt).mappings().all()


def list_course_grades(db: Session, course_id: int) -> Sequence[RowMapping]:
    """Every canonical student_grades row for the course's grade items;
    grade stays whatever is stored (nullable) — never coerced.
    """
    stmt = (
        select(StudentGrade.student_id, StudentGrade.grade_item_id, StudentGrade.grade)
        .join(GradeItem, GradeItem.id == StudentGrade.grade_item_id)
        .where(GradeItem.course_id == course_id)
    )
    return db.execute(stmt).mappings().all()


def count_closed_sessions(db: Session, course_id: int) -> int:
    return db.execute(
        select(func.count())
        .select_from(AttendanceSession)
        .where(AttendanceSession.course_id == course_id, AttendanceSession.status == CLOSED_STATUS)
    ).scalar_one()


def present_closed_sessions_by_student(db: Session, course_id: int) -> dict[int, int]:
    """student_id -> number of this course's CLOSED sessions they have a
    record for (distinct sessions). Students with none are absent from
    the dict. OPEN sessions and other courses never count.
    """
    stmt = (
        select(
            AttendanceRecord.student_id,
            func.count(distinct(AttendanceRecord.attendance_session_id)).label("present"),
        )
        .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.attendance_session_id)
        .where(AttendanceSession.course_id == course_id, AttendanceSession.status == CLOSED_STATUS)
        .group_by(AttendanceRecord.student_id)
    )
    return {row.student_id: row.present for row in db.execute(stmt)}


def participation_values_by_student(db: Session, course_id: int) -> dict[int, list[int]]:
    """student_id -> every participation observation value in the
    course. Students with none are absent from the dict.
    """
    stmt = select(ParticipationObservation.student_id, ParticipationObservation.value).where(
        ParticipationObservation.course_id == course_id
    )
    values: dict[int, list[int]] = defaultdict(list)
    for row in db.execute(stmt):
        values[row.student_id].append(row.value)
    return dict(values)
