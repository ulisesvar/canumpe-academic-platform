"""HTTP-level tests for GET /me/evaluation and GET
/students/{student_id}/evaluation — role authorization and student
isolation. Calculation correctness itself is covered at the service
level in tests/integration/test_evaluation_calculation.py; these tests
prove the HTTP layer wires authentication/authorization correctly.
"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.api.helpers import (
    assign_grade_item_to_category,
    create_course,
    create_enrollment,
    create_grade_category,
    create_grade_item,
    create_student,
    create_student_grade,
    issue_test_admin_key,
    issue_test_student_key,
    revoke_test_key_by_plaintext,
)


def _seed_single_category_scheme(db_engine: Engine, account_number: str) -> tuple[int, int, str]:
    """One course, one student enrolled, one 100%-weighted category with
    one graded item. Returns (student_id, course_id, student_api_key).
    """
    student_id = create_student(db_engine, account_number=account_number)
    course_id = create_course(db_engine)
    create_enrollment(db_engine, student_id=student_id, course_id=course_id)
    item_id = create_grade_item(db_engine, course_id=course_id, name="Tarea 01")
    create_student_grade(
        db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("80")
    )
    category_id = create_grade_category(
        db_engine, course_id=course_id, name="Tasks", weight_percent=Decimal("100"), sort_order=1
    )
    assign_grade_item_to_category(db_engine, grade_item_id=item_id, category_id=category_id)
    key = issue_test_student_key(db_engine, account_number=account_number)
    return student_id, course_id, key


def test_student_key_gets_own_evaluation(client: TestClient, db_engine: Engine) -> None:
    student_id, course_id, key = _seed_single_category_scheme(db_engine, "60001")

    response = client.get("/me/evaluation", headers={"X-API-Key": key})

    assert response.status_code == 200
    body = response.json()
    assert body["student_id"] == student_id
    assert body["course_id"] == course_id
    assert body["current_score_100"] == 80.0
    assert body["current_grade_10"] == 8.0


def test_student_can_only_ever_see_their_own_evaluation(
    client: TestClient, db_engine: Engine
) -> None:
    _, _, key_a = _seed_single_category_scheme(db_engine, "60002")
    student_b, _, _ = _seed_single_category_scheme(db_engine, "60003")

    response = client.get("/me/evaluation", headers={"X-API-Key": key_a})

    assert response.json()["student_id"] != student_b


def test_student_key_on_admin_evaluation_route_returns_403(
    client: TestClient, db_engine: Engine
) -> None:
    student_id, _course_id, key = _seed_single_category_scheme(db_engine, "60004")

    response = client.get(f"/students/{student_id}/evaluation", headers={"X-API-Key": key})

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin API key required"}


def test_admin_key_can_read_any_students_evaluation(client: TestClient, db_engine: Engine) -> None:
    student_id, course_id, _ = _seed_single_category_scheme(db_engine, "60005")
    admin_key = issue_test_admin_key(db_engine)

    response = client.get(f"/students/{student_id}/evaluation", headers={"X-API-Key": admin_key})

    assert response.status_code == 200
    body = response.json()
    assert body["student_id"] == student_id
    assert body["course_id"] == course_id


def test_admin_key_on_me_evaluation_returns_403(client: TestClient, db_engine: Engine) -> None:
    admin_key = issue_test_admin_key(db_engine)

    response = client.get("/me/evaluation", headers={"X-API-Key": admin_key})

    assert response.status_code == 403
    assert response.json() == {"detail": "Student API key required"}


def test_missing_key_on_evaluation_returns_401(client: TestClient) -> None:
    response = client.get("/me/evaluation")

    assert response.status_code == 401


def test_invalid_key_on_evaluation_returns_401(client: TestClient) -> None:
    response = client.get("/me/evaluation", headers={"X-API-Key": "not-a-real-key"})

    assert response.status_code == 401


def test_revoked_key_on_evaluation_returns_401(client: TestClient, db_engine: Engine) -> None:
    _, _, key = _seed_single_category_scheme(db_engine, "60006")
    revoke_test_key_by_plaintext(db_engine, key)

    response = client.get("/me/evaluation", headers={"X-API-Key": key})

    assert response.status_code == 401


def test_unknown_student_via_admin_evaluation_route_returns_404(
    client: TestClient, db_engine: Engine
) -> None:
    admin_key = issue_test_admin_key(db_engine)

    response = client.get("/students/999999/evaluation", headers={"X-API-Key": admin_key})

    assert response.status_code == 404
    assert response.json() == {"detail": "Student not found"}
