from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine

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


def test_summary_works_for_a_populated_student(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="9001")
    course_id = create_course(db_engine)
    create_enrollment(db_engine, student_id=student_id, course_id=course_id)
    session_id = create_attendance_session(db_engine, course_id=course_id, opened_at=T0)
    create_attendance_record(
        db_engine, attendance_session_id=session_id, student_id=student_id, recorded_at=T0
    )
    graded_item = create_grade_item(db_engine, course_id=course_id, name="Graded")
    ungraded_item = create_grade_item(db_engine, course_id=course_id, name="Ungraded")
    create_student_grade(
        db_engine, grade_item_id=graded_item, student_id=student_id, grade=Decimal("30")
    )
    create_student_grade(db_engine, grade_item_id=ungraded_item, student_id=student_id, grade=None)

    response = client.get(f"/students/{student_id}/summary", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["student_id"] == student_id
    assert body["courses_count"] == 1
    assert body["attendance"]["sessions_recorded"] == 1
    assert body["grades"]["graded_items"] == 1
    assert body["grades"]["ungraded_items"] == 1


def test_summary_works_for_a_student_with_no_records(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="9002")

    response = client.get(f"/students/{student_id}/summary", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {
        "student_id": student_id,
        "courses_count": 0,
        "attendance": {"sessions_recorded": 0},
        "grades": {"graded_items": 0, "ungraded_items": 0},
    }


def test_summary_does_not_invent_gpa_or_averages(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="9003")
    course_id = create_course(db_engine)
    item_id = create_grade_item(db_engine, course_id=course_id)
    create_student_grade(
        db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("30")
    )

    response = client.get(f"/students/{student_id}/summary", headers=admin_headers)

    body_text = response.text.lower()
    for forbidden in ("gpa", "average", "mean", "score"):
        assert forbidden not in body_text


def test_summary_does_not_invent_attendance_percentage(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="9004")
    course_id = create_course(db_engine)
    session_id = create_attendance_session(db_engine, course_id=course_id, opened_at=T0)
    create_attendance_record(
        db_engine, attendance_session_id=session_id, student_id=student_id, recorded_at=T0
    )

    response = client.get(f"/students/{student_id}/summary", headers=admin_headers)

    body_text = response.text.lower()
    for forbidden in ("percentage", "percent", "rate", "risk", "pass", "fail"):
        assert forbidden not in body_text


def test_graded_vs_ungraded_count_is_correct(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="9005")
    course_id = create_course(db_engine)
    graded_ids = [
        create_grade_item(db_engine, course_id=course_id, name=f"G{i}") for i in range(2)
    ]
    ungraded_ids = [
        create_grade_item(db_engine, course_id=course_id, name=f"U{i}") for i in range(3)
    ]
    for item_id in graded_ids:
        create_student_grade(
            db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("50")
        )
    for item_id in ungraded_ids:
        create_student_grade(db_engine, grade_item_id=item_id, student_id=student_id, grade=None)

    response = client.get(f"/students/{student_id}/summary", headers=admin_headers)

    body = response.json()
    assert body["grades"]["graded_items"] == 2
    assert body["grades"]["ungraded_items"] == 3
