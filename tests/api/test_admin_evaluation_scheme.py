"""HTTP-level tests for GET/PUT /admin/courses/{course_id}/evaluation-scheme.

Payload validation itself (weight totals, duplicate assignment, cross-
course items, unknown items, atomicity) is covered at the service level
in tests/integration/test_evaluation_scheme_provisioning.py; these
tests prove the HTTP layer's authorization and the read contract.
"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.api.helpers import (
    assign_grade_item_to_category,
    create_course,
    create_grade_category,
    create_grade_item,
    create_student,
    issue_test_admin_key,
    issue_test_student_key,
    revoke_test_key_by_plaintext,
)

_VALID_PAYLOAD = {
    "categories": [
        {"name": "Tasks", "weight_percent": 60, "sort_order": 1, "grade_items": []},
        {"name": "Exams", "weight_percent": 40, "sort_order": 2, "grade_items": []},
    ]
}


def test_admin_can_read_the_evaluation_scheme(client: TestClient, db_engine: Engine) -> None:
    course_id = create_course(db_engine, name="Test Course")
    item_id = create_grade_item(db_engine, course_id=course_id, name="Tarea 01")
    category_id = create_grade_category(
        db_engine, course_id=course_id, name="Tasks", weight_percent=Decimal("100"), sort_order=1
    )
    assign_grade_item_to_category(db_engine, grade_item_id=item_id, category_id=category_id)
    admin_key = issue_test_admin_key(db_engine)

    response = client.get(
        f"/admin/courses/{course_id}/evaluation-scheme", headers={"X-API-Key": admin_key}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["course_id"] == course_id
    assert body["course_name"] == "Test Course"
    assert body["categories"][0]["name"] == "Tasks"
    assert body["categories"][0]["grade_items"][0]["grade_item_id"] == item_id


def test_student_key_on_scheme_read_returns_403(client: TestClient, db_engine: Engine) -> None:
    course_id = create_course(db_engine)
    create_student(db_engine, account_number="70001")
    student_key = issue_test_student_key(db_engine, account_number="70001")

    response = client.get(
        f"/admin/courses/{course_id}/evaluation-scheme", headers={"X-API-Key": student_key}
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin API key required"}


def test_unassigned_grade_items_are_reported(client: TestClient, db_engine: Engine) -> None:
    course_id = create_course(db_engine)
    create_grade_item(db_engine, course_id=course_id, name="Unassigned Item")
    admin_key = issue_test_admin_key(db_engine)

    response = client.get(
        f"/admin/courses/{course_id}/evaluation-scheme", headers={"X-API-Key": admin_key}
    )

    body = response.json()
    assert len(body["unassigned_grade_items"]) == 1
    assert body["unassigned_grade_items"][0]["name"] == "Unassigned Item"


def test_category_and_grade_item_ordering_is_deterministic(
    client: TestClient, db_engine: Engine
) -> None:
    course_id = create_course(db_engine)
    item_ids = [
        create_grade_item(db_engine, course_id=course_id, name=f"Item {i}") for i in range(3)
    ]
    category_id = create_grade_category(
        db_engine, course_id=course_id, name="Cat", weight_percent=Decimal("100"), sort_order=1
    )
    for item_id in reversed(item_ids):
        assign_grade_item_to_category(db_engine, grade_item_id=item_id, category_id=category_id)
    admin_key = issue_test_admin_key(db_engine)

    first = client.get(
        f"/admin/courses/{course_id}/evaluation-scheme", headers={"X-API-Key": admin_key}
    ).json()
    second = client.get(
        f"/admin/courses/{course_id}/evaluation-scheme", headers={"X-API-Key": admin_key}
    ).json()

    returned_ids = [gi["grade_item_id"] for gi in first["categories"][0]["grade_items"]]
    assert returned_ids == sorted(returned_ids)
    assert first == second


def test_admin_can_replace_the_evaluation_scheme(client: TestClient, db_engine: Engine) -> None:
    course_id = create_course(db_engine)
    admin_key = issue_test_admin_key(db_engine)

    response = client.put(
        f"/admin/courses/{course_id}/evaluation-scheme",
        headers={"X-API-Key": admin_key},
        json=_VALID_PAYLOAD,
    )

    assert response.status_code == 200
    names = {c["name"] for c in response.json()["categories"]}
    assert names == {"Tasks", "Exams"}


def test_student_key_cannot_write_the_evaluation_scheme(
    client: TestClient, db_engine: Engine
) -> None:
    course_id = create_course(db_engine)
    create_student(db_engine, account_number="70002")
    student_key = issue_test_student_key(db_engine, account_number="70002")

    response = client.put(
        f"/admin/courses/{course_id}/evaluation-scheme",
        headers={"X-API-Key": student_key},
        json=_VALID_PAYLOAD,
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin API key required"}


def test_missing_key_on_scheme_write_returns_401(client: TestClient, db_engine: Engine) -> None:
    course_id = create_course(db_engine)

    response = client.put(
        f"/admin/courses/{course_id}/evaluation-scheme", json=_VALID_PAYLOAD
    )

    assert response.status_code == 401


def test_revoked_admin_key_on_scheme_write_returns_401(
    client: TestClient, db_engine: Engine
) -> None:
    course_id = create_course(db_engine)
    admin_key = issue_test_admin_key(db_engine)
    revoke_test_key_by_plaintext(db_engine, admin_key)

    response = client.put(
        f"/admin/courses/{course_id}/evaluation-scheme",
        headers={"X-API-Key": admin_key},
        json=_VALID_PAYLOAD,
    )

    assert response.status_code == 401


def test_invalid_scheme_payload_returns_400(client: TestClient, db_engine: Engine) -> None:
    course_id = create_course(db_engine)
    admin_key = issue_test_admin_key(db_engine)

    response = client.put(
        f"/admin/courses/{course_id}/evaluation-scheme",
        headers={"X-API-Key": admin_key},
        json={
            "categories": [
                {"name": "Tasks", "weight_percent": 90, "sort_order": 1, "grade_items": []}
            ]
        },
    )

    assert response.status_code == 400
