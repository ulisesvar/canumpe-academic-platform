"""/me/* — student_id comes exclusively from the authenticated STUDENT
API key (app.auth.dependencies.require_student), never from client
input. There is no parameter through which a client could even attempt
to request another student's data.
"""

from datetime import UTC, datetime, timedelta
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
    issue_test_student_key,
)

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def test_me_returns_own_identity(client: TestClient, db_engine: Engine) -> None:
    student_id = create_student(db_engine, account_number="30001")
    key = issue_test_student_key(db_engine, account_number="30001")

    response = client.get("/me", headers={"X-API-Key": key})

    assert response.status_code == 200
    assert response.json() == {"student_id": student_id, "account_number": "30001"}


def test_me_identity_never_exposes_the_api_key_hash_or_id(
    client: TestClient, db_engine: Engine
) -> None:
    create_student(db_engine, account_number="30002")
    key = issue_test_student_key(db_engine, account_number="30002")

    response = client.get("/me", headers={"X-API-Key": key})

    assert set(response.json().keys()) == {"student_id", "account_number"}


def test_me_courses_returns_own_courses(client: TestClient, db_engine: Engine) -> None:
    student_id = create_student(db_engine, account_number="30003")
    key = issue_test_student_key(db_engine, account_number="30003")
    course_id = create_course(db_engine, name="Intro to Programming")
    create_enrollment(db_engine, student_id=student_id, course_id=course_id)

    response = client.get("/me/courses", headers={"X-API-Key": key})

    assert response.status_code == 200
    body = response.json()
    assert body["student_id"] == student_id
    assert [c["course_id"] for c in body["courses"]] == [course_id]


def test_me_attendance_returns_own_attendance_without_inferring_absence(
    client: TestClient, db_engine: Engine
) -> None:
    student_id = create_student(db_engine, account_number="30004")
    key = issue_test_student_key(db_engine, account_number="30004")
    course_id = create_course(db_engine)
    attended = create_attendance_session(db_engine, course_id=course_id, opened_at=T0)
    create_attendance_session(db_engine, course_id=course_id, opened_at=T0 + timedelta(days=1))
    create_attendance_record(
        db_engine, attendance_session_id=attended, student_id=student_id, recorded_at=T0
    )

    response = client.get("/me/attendance", headers={"X-API-Key": key})

    assert response.status_code == 200
    body = response.json()
    # Only the one recorded session — never a synthesized "absent" entry
    # for the session the student has no record for.
    assert len(body["attendance"]) == 1
    assert body["attendance"][0]["present"] is True


def test_me_grades_preserves_null_and_zero_semantics(
    client: TestClient, db_engine: Engine
) -> None:
    student_id = create_student(db_engine, account_number="30005")
    key = issue_test_student_key(db_engine, account_number="30005")
    course_id = create_course(db_engine)
    ungraded_item = create_grade_item(db_engine, course_id=course_id, name="Ungraded")
    zero_item = create_grade_item(db_engine, course_id=course_id, name="Zero")
    create_student_grade(db_engine, grade_item_id=ungraded_item, student_id=student_id, grade=None)
    create_student_grade(
        db_engine, grade_item_id=zero_item, student_id=student_id, grade=Decimal("0")
    )

    response = client.get("/me/grades", headers={"X-API-Key": key})

    grades_by_item = {g["grade_item_id"]: g["grade"] for g in response.json()["grades"]}
    assert grades_by_item[ungraded_item] is None
    assert grades_by_item[zero_item] == 0
    assert grades_by_item[zero_item] is not None


def test_me_summary_reflects_own_data(client: TestClient, db_engine: Engine) -> None:
    student_id = create_student(db_engine, account_number="30006")
    key = issue_test_student_key(db_engine, account_number="30006")
    course_id = create_course(db_engine)
    create_enrollment(db_engine, student_id=student_id, course_id=course_id)

    response = client.get("/me/summary", headers={"X-API-Key": key})

    assert response.status_code == 200
    body = response.json()
    assert body["student_id"] == student_id
    assert body["courses_count"] == 1


def test_client_supplied_student_id_is_ignored_on_me_routes(
    client: TestClient, db_engine: Engine
) -> None:
    """/me/* has no student_id parameter at all — a client attempting to
    smuggle one in as a query string must have no effect whatsoever.
    """
    student_id = create_student(db_engine, account_number="30007")
    key = issue_test_student_key(db_engine, account_number="30007")

    response = client.get("/me?student_id=999999", headers={"X-API-Key": key})

    assert response.status_code == 200
    assert response.json()["student_id"] == student_id


def test_student_a_key_can_never_return_student_b_data(
    client: TestClient, db_engine: Engine
) -> None:
    create_student(db_engine, account_number="30008")
    student_b = create_student(db_engine, account_number="30009")
    key_a = issue_test_student_key(db_engine, account_number="30008")
    course_id = create_course(db_engine)
    create_enrollment(db_engine, student_id=student_b, course_id=course_id)

    response = client.get("/me/courses", headers={"X-API-Key": key_a})

    assert response.json()["student_id"] != student_b
    assert response.json()["courses"] == []
