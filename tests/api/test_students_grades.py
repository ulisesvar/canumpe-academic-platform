from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.api.helpers import (
    create_course,
    create_grade_item,
    create_student,
    create_student_grade,
)


def test_grades_endpoint_returns_canonical_grade_items(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="8001")
    course_id = create_course(db_engine)
    item_id = create_grade_item(
        db_engine,
        course_id=course_id,
        name="Tarea 01 — Identificación de Configuration Items",
        max_grade=Decimal("100"),
        activity_type="assign",
    )
    create_student_grade(
        db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("30")
    )

    response = client.get(f"/students/{student_id}/grades", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["student_id"] == student_id
    assert len(body["grades"]) == 1
    entry = body["grades"][0]
    assert entry["course_id"] == course_id
    assert entry["grade_item_id"] == item_id


def test_grade_30_serializes_correctly(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="8002")
    course_id = create_course(db_engine)
    item_id = create_grade_item(db_engine, course_id=course_id, max_grade=Decimal("100.00000"))
    create_student_grade(
        db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("30.00000")
    )

    response = client.get(f"/students/{student_id}/grades", headers=admin_headers)

    grade = response.json()["grades"][0]["grade"]
    assert grade == 30
    assert isinstance(grade, int | float)


def test_grade_75_serializes_correctly(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="8003")
    course_id = create_course(db_engine)
    item_id = create_grade_item(db_engine, course_id=course_id, max_grade=Decimal("100.00000"))
    create_student_grade(
        db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("75.00000")
    )

    response = client.get(f"/students/{student_id}/grades", headers=admin_headers)

    grade = response.json()["grades"][0]["grade"]
    assert grade == 75
    assert isinstance(grade, int | float)


def test_null_grade_serializes_as_json_null(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="8004")
    course_id = create_course(db_engine)
    item_id = create_grade_item(db_engine, course_id=course_id)
    create_student_grade(db_engine, grade_item_id=item_id, student_id=student_id, grade=None)

    response = client.get(f"/students/{student_id}/grades", headers=admin_headers)

    assert response.json()["grades"][0]["grade"] is None


def test_zero_grade_serializes_as_numeric_zero_not_null(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="8005")
    course_id = create_course(db_engine)
    item_id = create_grade_item(db_engine, course_id=course_id)
    create_student_grade(
        db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("0")
    )

    response = client.get(f"/students/{student_id}/grades", headers=admin_headers)

    grade = response.json()["grades"][0]["grade"]
    assert grade == 0
    assert grade is not None


def test_max_grade_is_returned_correctly(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="8006")
    course_id = create_course(db_engine)
    item_id = create_grade_item(db_engine, course_id=course_id, max_grade=Decimal("100.00000"))
    create_student_grade(
        db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("50")
    )

    response = client.get(f"/students/{student_id}/grades", headers=admin_headers)

    assert response.json()["grades"][0]["max_grade"] == 100


def test_activity_name_is_returned_correctly(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="8007")
    course_id = create_course(db_engine)
    item_id = create_grade_item(
        db_engine, course_id=course_id, name="Tarea 01 — Identificación de Configuration Items"
    )
    create_student_grade(
        db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("30")
    )

    response = client.get(f"/students/{student_id}/grades", headers=admin_headers)

    assert (
        response.json()["grades"][0]["name"]
        == "Tarea 01 — Identificación de Configuration Items"
    )


def test_source_ids_are_not_exposed(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="8008")
    course_id = create_course(db_engine)
    item_id = create_grade_item(db_engine, course_id=course_id)
    create_student_grade(
        db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("30")
    )

    response = client.get(f"/students/{student_id}/grades", headers=admin_headers)

    entry = response.json()["grades"][0]
    assert set(entry.keys()) == {
        "course_id",
        "grade_item_id",
        "name",
        "activity_type",
        "grade",
        "max_grade",
        "score_100",
        "category_id",
        "category_name",
        "category_weight_percent",
        "counts_toward_current_grade",
    }
    forbidden_substrings = ("source", "hash", "batch", "sync", "raw_", "moodle")
    body_text = response.text.lower()
    for forbidden in forbidden_substrings:
        assert forbidden not in body_text


def test_unrelated_students_grades_are_excluded(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_a = create_student(db_engine, account_number="8009")
    student_b = create_student(db_engine, account_number="8010")
    course_id = create_course(db_engine)
    item_a = create_grade_item(db_engine, course_id=course_id, name="Item A")
    item_b = create_grade_item(db_engine, course_id=course_id, name="Item B")
    create_student_grade(db_engine, grade_item_id=item_a, student_id=student_a, grade=Decimal("30"))
    create_student_grade(db_engine, grade_item_id=item_b, student_id=student_b, grade=Decimal("75"))

    response = client.get(f"/students/{student_a}/grades", headers=admin_headers)

    item_ids = [g["grade_item_id"] for g in response.json()["grades"]]
    assert item_ids == [item_a]


def test_grades_are_returned_in_deterministic_order(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="8011")
    course_id = create_course(db_engine)
    item_ids = [
        create_grade_item(db_engine, course_id=course_id, name=f"Item {i}") for i in range(5)
    ]
    for item_id in reversed(item_ids):
        create_student_grade(
            db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("50")
        )

    first = client.get(f"/students/{student_id}/grades", headers=admin_headers).json()
    second = client.get(f"/students/{student_id}/grades", headers=admin_headers).json()

    returned_ids = [g["grade_item_id"] for g in first["grades"]]
    assert returned_ids == sorted(returned_ids)
    assert first == second


def test_grades_endpoint_returns_empty_list_for_student_with_no_grades(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="8012")

    response = client.get(f"/students/{student_id}/grades", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {"student_id": student_id, "grades": []}
