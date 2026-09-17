"""Phase 7 enrichment of the existing GET /me/grades endpoint —
score_100 and evaluation-category metadata. Preservation of the
original grade/max_grade/name/activity_type, NULL-vs-zero semantics,
and per-student isolation are already covered by the Phase 5/6 tests in
tests/api/test_students_grades.py and tests/api/test_me.py; this file
covers only what's new in Phase 7.
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
    create_student_grade,
    issue_test_student_key,
)


def test_grades_endpoint_still_returns_individual_items_not_a_summary(
    client: TestClient, db_engine: Engine
) -> None:
    student_id = create_student(db_engine, account_number="80001")
    key = issue_test_student_key(db_engine, account_number="80001")
    course_id = create_course(db_engine)
    item_a = create_grade_item(db_engine, course_id=course_id, name="Item A")
    item_b = create_grade_item(db_engine, course_id=course_id, name="Item B")
    create_student_grade(
        db_engine, grade_item_id=item_a, student_id=student_id, grade=Decimal("50")
    )
    create_student_grade(
        db_engine, grade_item_id=item_b, student_id=student_id, grade=Decimal("90")
    )

    response = client.get("/me/grades", headers={"X-API-Key": key})

    grades = response.json()["grades"]
    assert len(grades) == 2
    assert {g["grade_item_id"] for g in grades} == {item_a, item_b}


def test_score_100_is_returned_for_a_graded_item(client: TestClient, db_engine: Engine) -> None:
    student_id = create_student(db_engine, account_number="80002")
    key = issue_test_student_key(db_engine, account_number="80002")
    course_id = create_course(db_engine)
    item_id = create_grade_item(db_engine, course_id=course_id, max_grade=Decimal("20"))
    create_student_grade(
        db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("18")
    )

    response = client.get("/me/grades", headers={"X-API-Key": key})

    assert response.json()["grades"][0]["score_100"] == 90.0


def test_score_100_is_null_when_grade_is_null(client: TestClient, db_engine: Engine) -> None:
    student_id = create_student(db_engine, account_number="80003")
    key = issue_test_student_key(db_engine, account_number="80003")
    course_id = create_course(db_engine)
    item_id = create_grade_item(db_engine, course_id=course_id)
    create_student_grade(db_engine, grade_item_id=item_id, student_id=student_id, grade=None)

    response = client.get("/me/grades", headers={"X-API-Key": key})

    assert response.json()["grades"][0]["score_100"] is None


def test_category_metadata_is_returned_when_configured(
    client: TestClient, db_engine: Engine
) -> None:
    student_id = create_student(db_engine, account_number="80004")
    key = issue_test_student_key(db_engine, account_number="80004")
    course_id = create_course(db_engine)
    item_id = create_grade_item(db_engine, course_id=course_id)
    create_student_grade(
        db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("75")
    )
    category_id = create_grade_category(
        db_engine, course_id=course_id, name="Tareas", weight_percent=Decimal("30"), sort_order=1
    )
    assign_grade_item_to_category(
        db_engine,
        grade_item_id=item_id,
        category_id=category_id,
        counts_toward_current_grade=True,
    )

    response = client.get("/me/grades", headers={"X-API-Key": key})

    entry = response.json()["grades"][0]
    assert entry["category_id"] == category_id
    assert entry["category_name"] == "Tareas"
    assert entry["category_weight_percent"] == 30.0
    assert entry["counts_toward_current_grade"] is True


def test_unconfigured_item_has_null_category_and_false_counts(
    client: TestClient, db_engine: Engine
) -> None:
    student_id = create_student(db_engine, account_number="80005")
    key = issue_test_student_key(db_engine, account_number="80005")
    course_id = create_course(db_engine)
    item_id = create_grade_item(db_engine, course_id=course_id)
    create_student_grade(
        db_engine, grade_item_id=item_id, student_id=student_id, grade=Decimal("50")
    )

    response = client.get("/me/grades", headers={"X-API-Key": key})

    entry = response.json()["grades"][0]
    assert entry["category_id"] is None
    assert entry["category_name"] is None
    assert entry["category_weight_percent"] is None
    assert entry["counts_toward_current_grade"] is False


def test_future_non_counted_item_remains_visible_in_grades_list(
    client: TestClient, db_engine: Engine
) -> None:
    """counts_toward_current_grade=false must not hide the item from
    /me/grades — only from the evaluation calculation.
    """
    student_id = create_student(db_engine, account_number="80006")
    key = issue_test_student_key(db_engine, account_number="80006")
    course_id = create_course(db_engine)
    future_item = create_grade_item(db_engine, course_id=course_id, name="Tarea 02 (futura)")
    create_student_grade(db_engine, grade_item_id=future_item, student_id=student_id, grade=None)
    category_id = create_grade_category(
        db_engine, course_id=course_id, name="Tareas", weight_percent=Decimal("100"), sort_order=1
    )
    assign_grade_item_to_category(
        db_engine,
        grade_item_id=future_item,
        category_id=category_id,
        counts_toward_current_grade=False,
    )

    response = client.get("/me/grades", headers={"X-API-Key": key})

    grades = response.json()["grades"]
    assert len(grades) == 1
    assert grades[0]["name"] == "Tarea 02 (futura)"
    assert grades[0]["counts_toward_current_grade"] is False
