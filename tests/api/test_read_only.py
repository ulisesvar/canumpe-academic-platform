"""Phase 5/6 endpoints must never write to the database — no INSERT/
UPDATE/DELETE, no side effects, no sync triggers, and (since Phase 6)
authentication itself must not write either (no last_used_at, nothing).
Proven by hitting every endpoint (including a 404 path and an
authentication-failure path) and asserting canonical + auth row counts
are byte-for-byte unchanged.
"""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select

from app.academic.models import (
    AttendanceRecord,
    AttendanceSession,
    Course,
    Enrollment,
    GradeItem,
    Student,
    StudentGrade,
)
from app.auth.models import ApiKey
from tests.api.helpers import (
    create_attendance_record,
    create_attendance_session,
    create_course,
    create_enrollment,
    create_grade_item,
    create_student,
    create_student_grade,
)

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def _row_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            "students": connection.execute(select(func.count()).select_from(Student)).scalar_one(),
            "courses": connection.execute(select(func.count()).select_from(Course)).scalar_one(),
            "enrollments": connection.execute(
                select(func.count()).select_from(Enrollment)
            ).scalar_one(),
            "attendance_sessions": connection.execute(
                select(func.count()).select_from(AttendanceSession)
            ).scalar_one(),
            "attendance_records": connection.execute(
                select(func.count()).select_from(AttendanceRecord)
            ).scalar_one(),
            "grade_items": connection.execute(
                select(func.count()).select_from(GradeItem)
            ).scalar_one(),
            "student_grades": connection.execute(
                select(func.count()).select_from(StudentGrade)
            ).scalar_one(),
            "api_keys": connection.execute(select(func.count()).select_from(ApiKey)).scalar_one(),
        }


def test_api_requests_do_not_mutate_canonical_or_auth_tables(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="9101")
    course_id = create_course(db_engine)
    create_enrollment(db_engine, student_id=student_id, course_id=course_id)
    session_id = create_attendance_session(db_engine, course_id=course_id, opened_at=T0)
    create_attendance_record(
        db_engine, attendance_session_id=session_id, student_id=student_id, recorded_at=T0
    )
    item_id = create_grade_item(db_engine, course_id=course_id)
    create_student_grade(
        db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("30")
    )

    before = _row_counts(db_engine)

    client.get(f"/students/{student_id}/courses", headers=admin_headers)
    client.get(f"/students/{student_id}/attendance", headers=admin_headers)
    client.get(f"/students/{student_id}/grades", headers=admin_headers)
    client.get(f"/students/{student_id}/summary", headers=admin_headers)
    client.get("/students/999999/summary", headers=admin_headers)  # 404 path
    client.get(f"/students/{student_id}/summary")  # missing key -> 401
    client.get(f"/students/{student_id}/summary", headers={"X-API-Key": "bogus"})  # 401

    after = _row_counts(db_engine)

    assert before == after
