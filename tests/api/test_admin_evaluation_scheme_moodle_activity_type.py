"""moodle_activity_type on GET/PUT /admin/courses/{course_id}/evaluation-scheme."""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.api.helpers import create_course, create_grade_category, issue_test_admin_key

# A payload exactly as a Phase 7/8 client sends it: no moodle_activity_type anywhere.
_LEGACY_PAYLOAD = {
    "categories": [
        {"name": "Tasks", "weight_percent": 60, "sort_order": 1, "grade_items": []},
        {"name": "Exams", "weight_percent": 40, "sort_order": 2, "grade_items": []},
    ]
}


def _url(course_id: int) -> str:
    return f"/admin/courses/{course_id}/evaluation-scheme"


def _types(client: TestClient, headers: dict[str, str], course_id: int) -> dict[str, str | None]:
    body = client.get(_url(course_id), headers=headers).json()
    return {c["name"]: c["moodle_activity_type"] for c in body["categories"]}


def test_put_stores_and_get_returns_the_moodle_activity_types(
    client: TestClient, db_engine: Engine
) -> None:
    course_id = create_course(db_engine)
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}
    payload = {
        "categories": [
            {
                "name": "Entregables / tareas",
                "weight_percent": 40,
                "sort_order": 1,
                "moodle_activity_type": "assign",
            },
            {
                "name": "Participación / asistencia",
                "weight_percent": 20,
                "sort_order": 2,
                "calculation_type": "ATTENDANCE_PARTICIPATION",
            },
            {
                "name": "Exámenes",
                "weight_percent": 40,
                "sort_order": 3,
                "moodle_activity_type": "quiz",
            },
        ]
    }

    response = client.put(_url(course_id), headers=headers, json=payload)

    assert response.status_code == 200
    assert _types(client, headers, course_id) == {
        "Entregables / tareas": "assign",
        "Participación / asistencia": None,
        "Exámenes": "quiz",
    }


def test_existing_clients_may_omit_the_field_and_it_is_null(
    client: TestClient, db_engine: Engine
) -> None:
    course_id = create_course(db_engine)
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}

    response = client.put(_url(course_id), headers=headers, json=_LEGACY_PAYLOAD)

    assert response.status_code == 200
    assert {c["moodle_activity_type"] for c in response.json()["categories"]} == {None}


def test_get_exposes_the_field_for_every_category(client: TestClient, db_engine: Engine) -> None:
    course_id = create_course(db_engine)
    create_grade_category(
        db_engine,
        course_id=course_id,
        name="Tareas",
        weight_percent=Decimal("100"),
        sort_order=1,
        moodle_activity_type="assign",
    )
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}

    category = client.get(_url(course_id), headers=headers).json()["categories"][0]

    assert category["moodle_activity_type"] == "assign"


def test_get_output_can_be_put_back_unchanged(client: TestClient, db_engine: Engine) -> None:
    course_id = create_course(db_engine)
    create_grade_category(
        db_engine,
        course_id=course_id,
        name="Tareas",
        weight_percent=Decimal("60"),
        sort_order=1,
        moodle_activity_type="assign",
    )
    create_grade_category(
        db_engine,
        course_id=course_id,
        name="Exámenes",
        weight_percent=Decimal("40"),
        sort_order=2,
        moodle_activity_type="quiz",
    )
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}
    scheme = client.get(_url(course_id), headers=headers).json()

    response = client.put(_url(course_id), headers=headers, json=scheme)

    assert response.status_code == 200
    assert _types(client, headers, course_id) == {"Tareas": "assign", "Exámenes": "quiz"}


def test_a_put_that_omits_the_field_clears_it(client: TestClient, db_engine: Engine) -> None:
    """Documents the specified behavior: omitting moodle_activity_type means NULL,
    and the PUT replaces the whole scheme — so a client that never sends the field
    removes an existing mapping. (GET -> PUT round trips keep it; see above.)"""
    course_id = create_course(db_engine)
    create_grade_category(
        db_engine,
        course_id=course_id,
        name="Tasks",
        weight_percent=Decimal("60"),
        sort_order=1,
        moodle_activity_type="assign",
    )
    create_grade_category(
        db_engine,
        course_id=course_id,
        name="Exams",
        weight_percent=Decimal("40"),
        sort_order=2,
        moodle_activity_type="quiz",
    )
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}

    client.put(_url(course_id), headers=headers, json=_LEGACY_PAYLOAD)

    assert _types(client, headers, course_id) == {"Tasks": None, "Exams": None}


def test_duplicate_moodle_activity_types_return_400(client: TestClient, db_engine: Engine) -> None:
    course_id = create_course(db_engine)
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}
    payload = {
        "categories": [
            {"name": "A", "weight_percent": 50, "sort_order": 1, "moodle_activity_type": "assign"},
            {"name": "B", "weight_percent": 50, "sort_order": 2, "moodle_activity_type": "assign"},
        ]
    }

    response = client.put(_url(course_id), headers=headers, json=payload)

    assert response.status_code == 400
    assert "assign" in response.json()["detail"]
    assert client.get(_url(course_id), headers=headers).json()["categories"] == []


def test_attendance_participation_with_a_moodle_type_returns_400(
    client: TestClient, db_engine: Engine
) -> None:
    course_id = create_course(db_engine)
    headers = {"X-API-Key": issue_test_admin_key(db_engine)}
    payload = {
        "categories": [
            {
                "name": "Participación",
                "weight_percent": 100,
                "sort_order": 1,
                "calculation_type": "ATTENDANCE_PARTICIPATION",
                "moodle_activity_type": "assign",
            }
        ]
    }

    response = client.put(_url(course_id), headers=headers, json=payload)

    assert response.status_code == 400
