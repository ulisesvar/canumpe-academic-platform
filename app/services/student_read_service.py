"""Read-model logic for the Phase 5 student API.

Owns the one business rule the repository layer can't: distinguishing
"student does not exist" (404, via StudentNotFoundError) from "student
exists but has no records" (200, empty collections) — see
app.repositories.student_read_repository.student_exists.

Decimal -> float conversion for grade fields happens here, once, so no
raw PostgreSQL NUMERIC ever reaches a Pydantic response model or JSON
serialization directly.
"""

from sqlalchemy.orm import Session

from app.api.schemas.students import (
    AttendanceEvent,
    AttendanceSummary,
    CourseEnrollment,
    GradeEntry,
    GradesSummary,
    StudentAttendanceResponse,
    StudentCourseResponse,
    StudentGradeResponse,
    StudentSummaryResponse,
)
from app.repositories import student_read_repository as repo


class StudentNotFoundError(Exception):
    """Raised when the requested canonical academic.students.id doesn't exist."""

    def __init__(self, student_id: int) -> None:
        self.student_id = student_id
        super().__init__(f"student_id={student_id!r} does not exist")


def _ensure_student_exists(db: Session, student_id: int) -> None:
    if not repo.student_exists(db, student_id):
        raise StudentNotFoundError(student_id)


def get_student_courses(db: Session, student_id: int) -> StudentCourseResponse:
    _ensure_student_exists(db, student_id)
    rows = repo.list_enrolled_courses(db, student_id)
    return StudentCourseResponse(
        student_id=student_id,
        courses=[
            CourseEnrollment(course_id=row["id"], name=row["name"], active=row["active"])
            for row in rows
        ],
    )


def get_student_attendance(db: Session, student_id: int) -> StudentAttendanceResponse:
    _ensure_student_exists(db, student_id)
    rows = repo.list_attendance_records(db, student_id)
    return StudentAttendanceResponse(
        student_id=student_id,
        attendance=[
            AttendanceEvent(
                course_id=row["course_id"],
                session_id=row["attendance_session_id"],
                session_date=row["opened_at"],
                present=True,
            )
            for row in rows
        ],
    )


def get_student_grades(db: Session, student_id: int) -> StudentGradeResponse:
    _ensure_student_exists(db, student_id)
    rows = repo.list_student_grades(db, student_id)
    return StudentGradeResponse(
        student_id=student_id,
        grades=[
            GradeEntry(
                course_id=row["course_id"],
                grade_item_id=row["id"],
                name=row["name"],
                activity_type=row["activity_type"],
                grade=float(row["grade"]) if row["grade"] is not None else None,
                max_grade=float(row["max_grade"]),
            )
            for row in rows
        ],
    )


def get_student_summary(db: Session, student_id: int) -> StudentSummaryResponse:
    _ensure_student_exists(db, student_id)
    courses = repo.list_enrolled_courses(db, student_id)
    attendance = repo.list_attendance_records(db, student_id)
    grades = repo.list_student_grades(db, student_id)

    graded_items = sum(1 for row in grades if row["grade"] is not None)
    ungraded_items = len(grades) - graded_items

    return StudentSummaryResponse(
        student_id=student_id,
        courses_count=len(courses),
        attendance=AttendanceSummary(sessions_recorded=len(attendance)),
        grades=GradesSummary(graded_items=graded_items, ungraded_items=ungraded_items),
    )
