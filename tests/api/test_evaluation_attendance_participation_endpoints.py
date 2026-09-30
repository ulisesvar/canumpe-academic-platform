"""GET /me/evaluation and GET /students/{student_id}/evaluation for a
course that has an ATTENDANCE_PARTICIPATION category (Phase 8.3): the
response SHAPE is exactly what it was in Phase 7 — no attendance,
participation or 33/67 fields — while the numbers include the category.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api.schemas.evaluation import (
    CategoryEvaluation,
    EvaluationItem,
    StudentEvaluationResponse,
)
from tests.api.helpers import (
    assign_grade_item_to_category,
    create_attendance_record,
    create_attendance_session,
    create_course,
    create_enrollment,
    create_grade_category,
    create_grade_item,
    create_participation_observation,
    create_student,
    create_student_grade,
    issue_test_admin_key,
    issue_test_student_key,
)

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

# Snapshot of the Phase 7 contract — must never grow attendance/participation keys.
RESPONSE_KEYS = {
    "student_id",
    "course_id",
    "weighted_points_earned",
    "evaluated_weight_percent",
    "current_score_100",
    "current_grade_10",
    "categories",
}
CATEGORY_KEYS = {
    "category_id",
    "name",
    "weight_percent",
    "category_score_100",
    "contribution_points",
    "counted_items",
    "graded_items",
    "ungraded_items",
    "items",
}
ITEM_KEYS = {
    "grade_item_id",
    "name",
    "activity_type",
    "grade",
    "max_grade",
    "score_100",
    "counts_toward_current_grade",
}


def _seed(
    db_engine: Engine,
    account_number: str,
    *,
    closed_sessions: int = 2,
    attended: int = 1,
    observations: tuple[int, ...] = (3, 3),
) -> tuple[int, int, str]:
    """Tasks 40% (graded 80) / Attendance-Participation 20% / Exams 40%
    (ungraded). Returns (student_id, course_id, student_key).
    """
    student_id = create_student(db_engine, account_number=account_number)
    course_id = create_course(db_engine)
    create_enrollment(db_engine, student_id=student_id, course_id=course_id)

    task = create_grade_item(db_engine, course_id=course_id, name="Tarea 01")
    exam = create_grade_item(db_engine, course_id=course_id, name="Examen 01")
    create_student_grade(db_engine, grade_item_id=task, student_id=student_id, grade=Decimal("80"))
    tasks_cat = create_grade_category(
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
    exams_cat = create_grade_category(
        db_engine, course_id=course_id, name="Exams", weight_percent=Decimal("40"), sort_order=3
    )
    assign_grade_item_to_category(db_engine, grade_item_id=task, category_id=tasks_cat)
    assign_grade_item_to_category(db_engine, grade_item_id=exam, category_id=exams_cat)

    for n in range(closed_sessions):
        session_id = create_attendance_session(
            db_engine, course_id=course_id, opened_at=T0 + timedelta(days=n), status="CLOSED"
        )
        if n < attended:
            create_attendance_record(
                db_engine, attendance_session_id=session_id, student_id=student_id, recorded_at=T0
            )
    for value in observations:
        create_participation_observation(
            db_engine, course_id=course_id, student_id=student_id, value=value
        )

    return student_id, course_id, issue_test_student_key(db_engine, account_number=account_number)


def _both(
    client: TestClient, db_engine: Engine, student_id: int, course_id: int, student_key: str
) -> tuple[dict, dict]:
    admin_key = issue_test_admin_key(db_engine)
    me = client.get(
        "/me/evaluation", params={"course_id": course_id}, headers={"X-API-Key": student_key}
    )
    admin = client.get(
        f"/students/{student_id}/evaluation",
        params={"course_id": course_id},
        headers={"X-API-Key": admin_key},
    )
    assert me.status_code == admin.status_code == 200
    return me.json(), admin.json()


def _category(body: dict, name: str) -> dict:
    return next(c for c in body["categories"] if c["name"] == name)


def test_response_schema_models_are_unchanged() -> None:
    assert set(StudentEvaluationResponse.model_fields) == RESPONSE_KEYS
    assert set(CategoryEvaluation.model_fields) == CATEGORY_KEYS
    assert set(EvaluationItem.model_fields) == ITEM_KEYS


def test_me_evaluation_response_shape_is_unchanged(client: TestClient, db_engine: Engine) -> None:
    student_id, course_id, key = _seed(db_engine, "8501")
    me, _ = _both(client, db_engine, student_id, course_id, key)

    assert set(me) == RESPONSE_KEYS
    for category in me["categories"]:
        assert set(category) == CATEGORY_KEYS
        for item in category["items"]:
            assert set(item) == ITEM_KEYS


def test_admin_student_evaluation_response_shape_is_unchanged(
    client: TestClient, db_engine: Engine
) -> None:
    student_id, course_id, key = _seed(db_engine, "8502")
    _, admin = _both(client, db_engine, student_id, course_id, key)

    assert set(admin) == RESPONSE_KEYS
    for category in admin["categories"]:
        assert set(category) == CATEGORY_KEYS
        for item in category["items"]:
            assert set(item) == ITEM_KEYS


def test_both_endpoints_return_identical_evaluations(client: TestClient, db_engine: Engine) -> None:
    student_id, course_id, key = _seed(db_engine, "8503")

    me, admin = _both(client, db_engine, student_id, course_id, key)

    assert me == admin


def test_attendance_participation_category_is_included_in_the_existing_fields(
    client: TestClient, db_engine: Engine
) -> None:
    student_id, course_id, key = _seed(db_engine, "8504")  # attendance 50, participation 100

    me, admin = _both(client, db_engine, student_id, course_id, key)

    for body in (me, admin):
        category = _category(body, "Attendance / Participation")
        assert category["items"] == []
        assert category["counted_items"] == 0
        assert category["weight_percent"] == 20.0
        assert category["category_score_100"] == 83.5  # 50 * 0.33 + 100 * 0.67
        assert category["contribution_points"] == 16.7  # 83.5 * 20 / 100
        assert body["evaluated_weight_percent"] == 60.0  # Tasks 40 + A/P 20; Exams ungraded
        assert body["weighted_points_earned"] == 48.7  # 32 + 16.7
        assert body["current_score_100"] == 81.17  # 48.7 / 60 * 100
        assert body["current_grade_10"] == 8.12


def test_grade_items_categories_keep_their_phase_7_numbers(
    client: TestClient, db_engine: Engine
) -> None:
    student_id, course_id, key = _seed(db_engine, "8505")

    me, _ = _both(client, db_engine, student_id, course_id, key)

    tasks = _category(me, "Tasks")
    assert tasks["category_score_100"] == 80.0
    assert tasks["contribution_points"] == 32.0
    assert (tasks["counted_items"], tasks["graded_items"], tasks["ungraded_items"]) == (1, 1, 0)
    assert tasks["items"][0]["grade"] == 80.0
    exams = _category(me, "Exams")
    assert exams["category_score_100"] is None
    assert exams["contribution_points"] is None


def test_missing_component_leaves_the_category_null_and_out_of_evaluated_weight(
    client: TestClient, db_engine: Engine
) -> None:
    student_id, course_id, key = _seed(db_engine, "8506", observations=())

    me, admin = _both(client, db_engine, student_id, course_id, key)

    for body in (me, admin):
        category = _category(body, "Attendance / Participation")
        assert category["category_score_100"] is None
        assert category["contribution_points"] is None
        assert body["evaluated_weight_percent"] == 40.0
        assert body["weighted_points_earned"] == 32.0
        assert body["current_score_100"] == 80.0
    assert me == admin
