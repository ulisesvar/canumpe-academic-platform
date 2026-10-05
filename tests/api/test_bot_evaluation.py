"""GET /bot/evaluation/{account_number} — the dedicated, read-only endpoint a
BOT API key (restricted to one course) may use. The course comes only from
the credential; the calculation is the shared get_student_evaluation, so
these tests prove wiring, isolation and NULL/zero preservation, not the
formulas themselves (covered in tests/integration/test_evaluation_calculation.py).
"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert

from app.academic.models import Enrollment
from tests.api.helpers import (
    assign_grade_item_to_category,
    create_course,
    create_enrollment,
    create_grade_category,
    create_grade_item,
    create_student,
    create_student_grade,
    issue_test_admin_key,
    issue_test_bot_key,
    issue_test_student_key,
    revoke_test_key_by_plaintext,
)

_NOT_FOUND = {"detail": "Student not found"}


def _seed_course_with_student(
    db_engine: Engine, account_number: str, grade: Decimal | int | None = 80
) -> tuple[int, int]:
    """A course with one 100%-weighted category holding one item, and one
    enrolled student with the given grade. Returns (student_id, course_id).
    """
    student_id = create_student(db_engine, account_number=account_number)
    course_id = create_course(db_engine, name=f"Course {account_number}")
    create_enrollment(db_engine, student_id=student_id, course_id=course_id)
    item_id = create_grade_item(db_engine, course_id=course_id, name="Tarea 01")
    create_student_grade(db_engine, grade_item_id=item_id, student_id=student_id, grade=grade)
    category_id = create_grade_category(
        db_engine, course_id=course_id, name="Tasks", weight_percent=Decimal("100"), sort_order=1
    )
    assign_grade_item_to_category(db_engine, grade_item_id=item_id, category_id=category_id)
    return student_id, course_id


def _get(client: TestClient, account_number: str, key: str):  # type: ignore[no-untyped-def]
    return client.get(f"/bot/evaluation/{account_number}", headers={"X-API-Key": key})


def test_valid_bot_key_returns_the_students_evaluation(
    client: TestClient, db_engine: Engine
) -> None:
    student_id, course_id = _seed_course_with_student(db_engine, "70001", grade=80)
    key = issue_test_bot_key(db_engine, course_id=course_id)

    response = _get(client, "70001", key)

    assert response.status_code == 200
    body = response.json()
    assert body["student_id"] == student_id
    assert body["course_id"] == course_id
    assert body["current_score_100"] == 80.0
    assert body["current_grade_10"] == 8.0
    assert body["evaluated_weight_percent"] == 100.0
    category = body["categories"][0]
    assert category["category_score_100"] == 80.0
    assert category["contribution_points"] == 80.0


def test_response_matches_the_existing_admin_student_evaluation_exactly(
    client: TestClient, db_engine: Engine
) -> None:
    student_id, course_id = _seed_course_with_student(db_engine, "70002", grade=65)
    bot_key = issue_test_bot_key(db_engine, course_id=course_id)
    admin_key = issue_test_admin_key(db_engine)

    via_bot = _get(client, "70002", bot_key).json()
    via_admin = client.get(
        f"/students/{student_id}/evaluation",
        params={"course_id": course_id},
        headers={"X-API-Key": admin_key},
    ).json()

    assert via_bot == via_admin


def test_missing_key_returns_401(client: TestClient, db_engine: Engine) -> None:
    _seed_course_with_student(db_engine, "70003")

    response = client.get("/bot/evaluation/70003")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}


def test_invalid_bot_key_returns_401(client: TestClient, db_engine: Engine) -> None:
    _seed_course_with_student(db_engine, "70004")

    response = _get(client, "70004", "canumpe_bot_" + "a" * 43)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}


def test_revoked_bot_key_returns_401(client: TestClient, db_engine: Engine) -> None:
    _, course_id = _seed_course_with_student(db_engine, "70005")
    key = issue_test_bot_key(db_engine, course_id=course_id)
    revoke_test_key_by_plaintext(db_engine, key)

    response = _get(client, "70005", key)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}


def test_student_key_returns_403(client: TestClient, db_engine: Engine) -> None:
    _seed_course_with_student(db_engine, "70006")
    key = issue_test_student_key(db_engine, account_number="70006")

    response = _get(client, "70006", key)

    assert response.status_code == 403
    assert response.json() == {"detail": "Bot API key required"}


def test_admin_key_returns_403(client: TestClient, db_engine: Engine) -> None:
    _seed_course_with_student(db_engine, "70007")
    key = issue_test_admin_key(db_engine)

    response = _get(client, "70007", key)

    assert response.status_code == 403
    assert response.json() == {"detail": "Bot API key required"}


def test_bot_key_is_rejected_on_every_other_route_family(
    client: TestClient, db_engine: Engine
) -> None:
    student_id, course_id = _seed_course_with_student(db_engine, "70008")
    key = issue_test_bot_key(db_engine, course_id=course_id)
    headers = {"X-API-Key": key}

    admin_requests = [
        ("GET", f"/admin/courses/{course_id}/gradebook", None),
        ("GET", f"/admin/courses/{course_id}/students", None),
        ("GET", f"/admin/courses/{course_id}/evaluation-scheme", None),
        ("GET", f"/admin/courses/{course_id}/students/{student_id}/participation", None),
        ("POST", f"/admin/courses/{course_id}/students/{student_id}/participation", {"value": 3}),
        ("PUT", f"/admin/courses/{course_id}/evaluation-scheme", {"categories": []}),
        ("DELETE", f"/admin/courses/{course_id}/students/{student_id}/participation/1", None),
    ]
    student_requests = [
        ("GET", f"/students/{student_id}/{path}", None)
        for path in ("courses", "attendance", "grades", "summary", "evaluation")
    ]
    me_requests = [
        ("GET", f"/me{path}", None)
        for path in ("", "/courses", "/attendance", "/grades", "/summary", "/evaluation")
    ]

    for method, path, payload in admin_requests + student_requests + me_requests:
        response = client.request(method, path, headers=headers, json=payload)
        assert response.status_code == 403, f"expected 403 for {method} {path}"


def test_bot_key_cannot_read_the_whole_course_gradebook(
    client: TestClient, db_engine: Engine
) -> None:
    _, course_id = _seed_course_with_student(db_engine, "70009")
    key = issue_test_bot_key(db_engine, course_id=course_id)

    response = client.get(f"/admin/courses/{course_id}/gradebook", headers={"X-API-Key": key})

    assert response.status_code == 403
    assert "students" not in response.json()


def test_bot_key_is_restricted_to_its_own_course(client: TestClient, db_engine: Engine) -> None:
    _, course_a = _seed_course_with_student(db_engine, "70010", grade=90)
    student_b, course_b = _seed_course_with_student(db_engine, "70011", grade=40)
    key_a = issue_test_bot_key(db_engine, course_id=course_a)
    key_b = issue_test_bot_key(db_engine, course_id=course_b)

    # Each key reaches only the student enrolled in ITS course ...
    assert _get(client, "70010", key_a).json()["course_id"] == course_a
    body_b = _get(client, "70011", key_b).json()
    assert body_b["course_id"] == course_b
    assert body_b["student_id"] == student_b
    # ... and gets the same 404 for a student that exists only in the other course.
    assert _get(client, "70011", key_a).status_code == 404
    assert _get(client, "70010", key_b).status_code == 404


def test_client_cannot_override_the_course(client: TestClient, db_engine: Engine) -> None:
    _, course_a = _seed_course_with_student(db_engine, "70012")
    student_b, course_b = _seed_course_with_student(db_engine, "70013")
    key_a = issue_test_bot_key(db_engine, course_id=course_a)

    response = client.get(
        "/bot/evaluation/70013",
        params={"course_id": course_b},
        headers={"X-API-Key": key_a, "X-Course-Id": str(course_b)},
    )

    assert response.status_code == 404
    assert response.json() == _NOT_FOUND


def test_nonexistent_account_number_returns_404(client: TestClient, db_engine: Engine) -> None:
    _, course_id = _seed_course_with_student(db_engine, "70014")
    key = issue_test_bot_key(db_engine, course_id=course_id)

    response = _get(client, "no-such-account", key)

    assert response.status_code == 404
    assert response.json() == _NOT_FOUND


def test_student_not_enrolled_in_the_bot_course_returns_the_same_404(
    client: TestClient, db_engine: Engine
) -> None:
    _, course_id = _seed_course_with_student(db_engine, "70015")
    create_student(db_engine, account_number="70016")  # exists, enrolled nowhere
    key = issue_test_bot_key(db_engine, course_id=course_id)

    unknown = _get(client, "no-such-account", key)
    unenrolled = _get(client, "70016", key)

    assert unenrolled.status_code == 404
    assert unenrolled.json() == _NOT_FOUND
    assert unenrolled.content == unknown.content


def test_inactive_enrollment_returns_404(client: TestClient, db_engine: Engine) -> None:
    _, course_id = _seed_course_with_student(db_engine, "70017")
    inactive_id = create_student(db_engine, account_number="70018")
    with db_engine.begin() as connection:
        connection.execute(
            insert(Enrollment).values(student_id=inactive_id, course_id=course_id, active=False)
        )
    key = issue_test_bot_key(db_engine, course_id=course_id)

    assert _get(client, "70018", key).status_code == 404


def test_null_stays_null_when_nothing_is_graded(client: TestClient, db_engine: Engine) -> None:
    _, course_id = _seed_course_with_student(db_engine, "70019", grade=None)
    key = issue_test_bot_key(db_engine, course_id=course_id)

    body = _get(client, "70019", key).json()

    assert body["current_score_100"] is None
    assert body["current_grade_10"] is None
    assert body["evaluated_weight_percent"] == 0.0
    category = body["categories"][0]
    assert category["category_score_100"] is None
    assert category["contribution_points"] is None
    assert category["items"][0]["grade"] is None
    assert category["items"][0]["score_100"] is None


def test_real_zero_stays_zero(client: TestClient, db_engine: Engine) -> None:
    _, course_id = _seed_course_with_student(db_engine, "70020", grade=0)
    key = issue_test_bot_key(db_engine, course_id=course_id)

    body = _get(client, "70020", key).json()

    assert body["current_score_100"] == 0.0
    assert body["current_grade_10"] == 0.0
    assert body["evaluated_weight_percent"] == 100.0
    category = body["categories"][0]
    assert category["category_score_100"] == 0.0
    assert category["items"][0]["grade"] == 0.0


def test_other_http_methods_are_not_allowed(client: TestClient, db_engine: Engine) -> None:
    _, course_id = _seed_course_with_student(db_engine, "70021")
    key = issue_test_bot_key(db_engine, course_id=course_id)

    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = client.request(method, "/bot/evaluation/70021", headers={"X-API-Key": key})
        assert response.status_code == 405, f"expected 405 for {method}"


def test_the_key_is_never_echoed_in_a_response(client: TestClient, db_engine: Engine) -> None:
    _, course_id = _seed_course_with_student(db_engine, "70022")
    key = issue_test_bot_key(db_engine, course_id=course_id)

    for account in ("70022", "no-such-account"):
        assert key not in _get(client, account, key).text
    assert key not in _get(client, "70022", key + "x").text
