"""Seed helpers for Phase 5 API tests.

Insert directly into academic.* with real, committed transactions — the
running API process reads through its own separate connection pool
(app.db.session), so data a test wants the API to see must actually be
committed, never left in an uncommitted SAVEPOINT.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine, insert

from app.academic.models import (
    AttendanceRecord,
    AttendanceSession,
    Course,
    Enrollment,
    GradeItem,
    Student,
    StudentGrade,
)


def create_student(engine: Engine, *, account_number: str) -> int:
    with engine.begin() as connection:
        return connection.execute(
            insert(Student)
            .values(account_number=account_number, first_name="Test", last_name="Student")
            .returning(Student.id)
        ).scalar_one()


def create_course(engine: Engine, *, name: str = "Test Course", active: bool = True) -> int:
    with engine.begin() as connection:
        return connection.execute(
            insert(Course).values(name=name, active=active).returning(Course.id)
        ).scalar_one()


def create_enrollment(engine: Engine, *, student_id: int, course_id: int) -> int:
    with engine.begin() as connection:
        return connection.execute(
            insert(Enrollment)
            .values(student_id=student_id, course_id=course_id)
            .returning(Enrollment.id)
        ).scalar_one()


def create_attendance_session(
    engine: Engine, *, course_id: int, opened_at: datetime, status: str = "OPEN"
) -> int:
    with engine.begin() as connection:
        return connection.execute(
            insert(AttendanceSession)
            .values(course_id=course_id, opened_at=opened_at, status=status)
            .returning(AttendanceSession.id)
        ).scalar_one()


def create_attendance_record(
    engine: Engine, *, attendance_session_id: int, student_id: int, recorded_at: datetime
) -> int:
    with engine.begin() as connection:
        return connection.execute(
            insert(AttendanceRecord)
            .values(
                attendance_session_id=attendance_session_id,
                student_id=student_id,
                recorded_at=recorded_at,
            )
            .returning(AttendanceRecord.id)
        ).scalar_one()


def create_grade_item(
    engine: Engine,
    *,
    course_id: int,
    name: str = "Tarea 01",
    max_grade: Decimal | int = 100,
    activity_type: str | None = "assign",
) -> int:
    with engine.begin() as connection:
        return connection.execute(
            insert(GradeItem)
            .values(
                course_id=course_id, name=name, max_grade=max_grade, activity_type=activity_type
            )
            .returning(GradeItem.id)
        ).scalar_one()


def create_student_grade(
    engine: Engine, *, grade_item_id: int, student_id: int, grade: Decimal | int | None
) -> int:
    with engine.begin() as connection:
        return connection.execute(
            insert(StudentGrade)
            .values(grade_item_id=grade_item_id, student_id=student_id, grade=grade)
            .returning(StudentGrade.id)
        ).scalar_one()
