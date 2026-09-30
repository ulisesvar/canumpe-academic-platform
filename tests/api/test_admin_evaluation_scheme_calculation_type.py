"""HTTP-level tests for calculation_type on GET/PUT
/admin/courses/{course_id}/evaluation-scheme (Phase 8.3), including the
guard that stops a Phase 7-style payload (no calculation_type) from
silently destroying an existing ATTENDANCE_PARTICIPATION category.
"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.api.helpers import (
    assign_grade_item_to_category,
    create_course,
    create_grade_category,
    create_grade_item,
    issue_test_admin_key,
)

# A payload exactly as a Phase 7 client sends it: no calculation_type anywhere.
_PHASE7_PAYLOAD = {
    "categories": [
        {"name": "Tasks", "weight_percent": 60, "sort_order": 1, "grade_items": []},
        {"name": "Exams", "weight_percent": 40, "sort_order": 2, "grade_items": []},
    ]
}


def _course_with_attendance_participation(db_engine: Engine) -> int:
    course_id = create_course(db_engine)
    create_grade_category(
        db_engine, course_id=course_id, name="Tasks", weight_percent=Decimal("40"), sort_order=1
    )
    create_grade_category(
        db_engine,
        course_id=course_id,
        name="Attendance / Participation",
        weight_percent=Decimal("20"),
        sort_order=2,
        calculation_type="ATTENDANCE_PARTICIPATION",
    )
    create_grade_category(
        db_engine, course_id=course_id, name="Exams", weight_percent=Decimal("40"), sort_order=3
    )
    return course_id


def _scheme_url(course_id: int) -> str:
    return f"/admin/courses/{course_id}/evaluation-scheme"


def _types(client: TestClient, headers: dict[str, str], course_id: int) -> dict[str, str]:
    body = client.get(_scheme_url(course_id), headers=headers).json()
    return {c["name"]: c["calculation_type"] for c in body["categories"]}


def test_get_scheme_exposes_calculation_type(client: TestClient, db_engine: Engine) -> None:
    course_id = _course_with_attendance_participation(db_engine)
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}

    assert _types(client, headers, course_id) == {
        "Tasks": "GRADE_ITEMS",
        "Attendance / Participation": "ATTENDANCE_PARTICIPATION",
        "Exams": "GRADE_ITEMS",
    }


def test_phase_7_payload_still_works_on_a_grade_items_only_course(
    client: TestClient, db_engine: Engine
) -> None:
    course_id = create_course(db_engine)
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}

    response = client.put(_scheme_url(course_id), headers=headers, json=_PHASE7_PAYLOAD)

    assert response.status_code == 200
    assert {c["name"]: c["calculation_type"] for c in response.json()["categories"]} == {
        "Tasks": "GRADE_ITEMS",
        "Exams": "GRADE_ITEMS",
    }


def test_phase_7_payload_cannot_reset_an_existing_attendance_participation_category(
    client: TestClient, db_engine: Engine
) -> None:
    course_id = _course_with_attendance_participation(db_engine)
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}
    before = client.get(_scheme_url(course_id), headers=headers).json()

    response = client.put(_scheme_url(course_id), headers=headers, json=_PHASE7_PAYLOAD)

    assert response.status_code == 400
    assert "ATTENDANCE_PARTICIPATION" in response.json()["detail"]
    assert client.get(_scheme_url(course_id), headers=headers).json() == before


def test_a_payload_that_includes_the_attendance_participation_category_is_accepted(
    client: TestClient, db_engine: Engine
) -> None:
    course_id = _course_with_attendance_participation(db_engine)
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}
    payload = {
        "categories": [
            {"name": "Tasks", "weight_percent": 50, "sort_order": 1},
            {
                "name": "Participación",
                "weight_percent": 10,
                "sort_order": 2,
                "calculation_type": "ATTENDANCE_PARTICIPATION",
            },
            {"name": "Exams", "weight_percent": 40, "sort_order": 3},
        ]
    }

    response = client.put(_scheme_url(course_id), headers=headers, json=payload)

    assert response.status_code == 200
    assert _types(client, headers, course_id) == {
        "Tasks": "GRADE_ITEMS",
        "Participación": "ATTENDANCE_PARTICIPATION",
        "Exams": "GRADE_ITEMS",
    }


def test_get_output_can_be_put_back_without_changing_calculation_types(
    client: TestClient, db_engine: Engine
) -> None:
    course_id = _course_with_attendance_participation(db_engine)
    item_id = create_grade_item(db_engine, course_id=course_id, name="Tarea 01")
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}
    tasks_id = next(
        c["category_id"]
        for c in client.get(_scheme_url(course_id), headers=headers).json()["categories"]
        if c["name"] == "Tasks"
    )
    assign_grade_item_to_category(db_engine, grade_item_id=item_id, category_id=tasks_id)
    scheme = client.get(_scheme_url(course_id), headers=headers).json()

    response = client.put(_scheme_url(course_id), headers=headers, json=scheme)

    assert response.status_code == 200
    assert _types(client, headers, course_id) == {
        "Tasks": "GRADE_ITEMS",
        "Attendance / Participation": "ATTENDANCE_PARTICIPATION",
        "Exams": "GRADE_ITEMS",
    }


def test_more_than_one_attendance_participation_category_returns_400(
    client: TestClient, db_engine: Engine
) -> None:
    course_id = create_course(db_engine)
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}

    response = client.put(
        _scheme_url(course_id),
        headers=headers,
        json={
            "categories": [
                {
                    "name": "A",
                    "weight_percent": 50,
                    "sort_order": 1,
                    "calculation_type": "ATTENDANCE_PARTICIPATION",
                },
                {
                    "name": "B",
                    "weight_percent": 50,
                    "sort_order": 2,
                    "calculation_type": "ATTENDANCE_PARTICIPATION",
                },
            ]
        },
    )

    assert response.status_code == 400
    assert client.get(_scheme_url(course_id), headers=headers).json()["categories"] == []


def test_attendance_participation_category_with_grade_items_returns_400(
    client: TestClient, db_engine: Engine
) -> None:
    course_id = create_course(db_engine)
    item_id = create_grade_item(db_engine, course_id=course_id)
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}

    response = client.put(
        _scheme_url(course_id),
        headers=headers,
        json={
            "categories": [
                {
                    "name": "A",
                    "weight_percent": 100,
                    "sort_order": 1,
                    "calculation_type": "ATTENDANCE_PARTICIPATION",
                    "grade_items": [
                        {"grade_item_id": item_id, "counts_toward_current_grade": True}
                    ],
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "cannot contain grade items" in response.json()["detail"]


def test_unknown_calculation_type_is_rejected(client: TestClient, db_engine: Engine) -> None:
    course_id = create_course(db_engine)
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}

    response = client.put(
        _scheme_url(course_id),
        headers=headers,
        json={
            "categories": [
                {"name": "A", "weight_percent": 100, "sort_order": 1, "calculation_type": "BOGUS"}
            ]
        },
    )

    assert response.status_code == 422
