"""HTTP-level tests for GET /admin/courses/{course_id}/gradebook.

Seeded scheme unless stated: Tasks 40% (sort_order 1), Attendance/
Participation 20% (sort_order 2, ATTENDANCE_PARTICIPATION), Exams 40%
(sort_order 3). The Exam item is deliberately created FIRST, so its
lower id must not beat its category's sort_order in the column order.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, insert
from sqlalchemy.orm import Session

from app.academic.models import (
    AttendanceRecord,
    AttendanceSession,
    Course,
    Enrollment,
    GradeItem,
    GradeItemEvaluation,
    ParticipationObservation,
    Student,
    StudentGrade,
)
from app.db import session as app_db_session
from app.services import evaluation_service
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
    revoke_test_key_by_plaintext,
)

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def _url(course_id: int) -> str:
    return f"/admin/courses/{course_id}/gradebook"


def _seed_scheme(db_engine: Engine, course_id: int) -> dict[str, int]:
    """Creates the Exam item first, then the Task items and an unassigned
    item, and the three categories. Returns item and category ids.
    """
    exam = create_grade_item(db_engine, course_id=course_id, name="Examen 01", max_grade=100)
    task1 = create_grade_item(db_engine, course_id=course_id, name="Tarea 01", max_grade=100)
    task2 = create_grade_item(db_engine, course_id=course_id, name="Tarea 02", max_grade=100)
    extra = create_grade_item(db_engine, course_id=course_id, name="Extra", max_grade=10)
    tasks = create_grade_category(
        db_engine, course_id=course_id, name="Tasks", weight_percent=Decimal("40"), sort_order=1
    )
    ap = create_grade_category(
        db_engine,
        course_id=course_id,
        name="Attendance / Participation",
        weight_percent=Decimal("20"),
        sort_order=2,
        calculation_type="ATTENDANCE_PARTICIPATION",
    )
    exams = create_grade_category(
        db_engine, course_id=course_id, name="Exams", weight_percent=Decimal("40"), sort_order=3
    )
    assign_grade_item_to_category(db_engine, grade_item_id=task1, category_id=tasks)
    assign_grade_item_to_category(db_engine, grade_item_id=task2, category_id=tasks)
    assign_grade_item_to_category(db_engine, grade_item_id=exam, category_id=exams)
    return {
        "exam": exam,
        "task1": task1,
        "task2": task2,
        "extra": extra,
        "tasks": tasks,
        "ap": ap,
        "exams": exams,
    }


def _seed_class(db_engine: Engine) -> dict[str, Any]:
    """Student A: Tarea 01 = 80, Tarea 02 = 0 (a real zero), Examen = NULL
    row; attended 3 of 4 closed sessions (plus an OPEN one); one
    participation observation of 2. Student B: no grade rows, no
    attendance, no participation.
    """
    course_id = create_course(db_engine, name="Gradebook Course")
    ids = _seed_scheme(db_engine, course_id)
    a = create_student(db_engine, account_number="8701")
    b = create_student(db_engine, account_number="8702")
    for student_id in (a, b):
        create_enrollment(db_engine, student_id=student_id, course_id=course_id)

    create_student_grade(db_engine, grade_item_id=ids["task1"], student_id=a, grade=Decimal("80"))
    create_student_grade(db_engine, grade_item_id=ids["task2"], student_id=a, grade=Decimal("0"))
    create_student_grade(db_engine, grade_item_id=ids["exam"], student_id=a, grade=None)

    for n in range(4):
        session_id = create_attendance_session(
            db_engine, course_id=course_id, opened_at=T0 + timedelta(days=n), status="CLOSED"
        )
        if n < 3:
            create_attendance_record(
                db_engine, attendance_session_id=session_id, student_id=a, recorded_at=T0
            )
    open_id = create_attendance_session(
        db_engine, course_id=course_id, opened_at=T0 + timedelta(days=9), status="OPEN"
    )
    create_attendance_record(db_engine, attendance_session_id=open_id, student_id=b, recorded_at=T0)

    create_participation_observation(db_engine, course_id=course_id, student_id=a, value=2)
    return {"course_id": course_id, "a": a, "b": b, **ids}


def _student_row(body: dict, student_id: int) -> dict:
    return next(s for s in body["students"] if s["student_id"] == student_id)


def _category(student: dict, name: str) -> dict:
    return next(c for c in student["categories"] if c["name"] == name)


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _all_keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _all_keys(v)}
    return set()


# -- structure ----------------------------------------------------------


def test_gradebook_includes_course_scheme_and_every_grade_item(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)

    body = client.get(_url(seed["course_id"]), headers=admin_headers).json()

    assert body["course"] == {"course_id": seed["course_id"], "name": "Gradebook Course"}
    assert [(c["name"], c["calculation_type"], c["weight_percent"]) for c in body["scheme"]] == [
        ("Tasks", "GRADE_ITEMS", 40.0),
        ("Attendance / Participation", "ATTENDANCE_PARTICIPATION", 20.0),
        ("Exams", "GRADE_ITEMS", 40.0),
    ]
    assert {c["activity_id"] for c in body["columns"]} == {
        seed["exam"],
        seed["task1"],
        seed["task2"],
        seed["extra"],
    }
    for student in body["students"]:
        assert len(student["grades"]) == 4
        assert [g["activity_id"] for g in student["grades"]] == [
            c["activity_id"] for c in body["columns"]
        ]


def test_grade_cells_carry_the_activity_details(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)

    body = client.get(_url(seed["course_id"]), headers=admin_headers).json()
    cell = next(
        g for g in _student_row(body, seed["a"])["grades"] if g["activity_id"] == seed["task1"]
    )

    assert cell == {
        "activity_id": seed["task1"],
        "name": "Tarea 01",
        "activity_type": "assign",
        "max_grade": 100.0,
        "category_id": seed["tasks"],
        "category_name": "Tasks",
        "counts_toward_current_grade": True,
        "grade": 80.0,
        "score_100": 80.0,
    }


def test_activity_order_is_category_sort_order_then_item_id_with_unassigned_last(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)

    first = client.get(_url(seed["course_id"]), headers=admin_headers).json()
    second = client.get(_url(seed["course_id"]), headers=admin_headers).json()

    # The Exam item has the LOWEST id but its category sorts last.
    assert [c["activity_id"] for c in first["columns"]] == [
        seed["task1"],
        seed["task2"],
        seed["exam"],
        seed["extra"],
    ]
    assert first["columns"] == second["columns"]
    extra = first["columns"][-1]
    assert (extra["category_id"], extra["category_name"], extra["counts_toward_current_grade"]) == (
        None,
        None,
        None,
    )


def test_students_are_ordered_like_the_roster(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)

    gradebook = client.get(_url(seed["course_id"]), headers=admin_headers).json()
    roster = client.get(
        f"/admin/courses/{seed['course_id']}/students", headers=admin_headers
    ).json()

    assert [s["student_id"] for s in gradebook["students"]] == [
        s["student_id"] for s in roster["students"]
    ]
    identity = gradebook["students"][0]
    assert identity["full_name"] == f"{identity['first_name']} {identity['last_name']}"
    assert identity["account_number"] in {"8701", "8702"}


# -- grade NULL semantics -----------------------------------------------


def test_null_grade_stays_null_and_missing_grade_row_is_null(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)

    body = client.get(_url(seed["course_id"]), headers=admin_headers).json()
    a_cells = {g["activity_id"]: g for g in _student_row(body, seed["a"])["grades"]}
    b_cells = {g["activity_id"]: g for g in _student_row(body, seed["b"])["grades"]}

    assert a_cells[seed["exam"]]["grade"] is None  # stored NULL
    assert a_cells[seed["exam"]]["score_100"] is None
    assert a_cells[seed["extra"]]["grade"] is None  # no row at all
    for cell in b_cells.values():
        assert cell["grade"] is None
        assert cell["score_100"] is None


def test_a_real_zero_grade_stays_zero(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)

    body = client.get(_url(seed["course_id"]), headers=admin_headers).json()
    a = _student_row(body, seed["a"])
    zero = next(g for g in a["grades"] if g["activity_id"] == seed["task2"])

    assert zero["grade"] == 0.0
    assert zero["score_100"] == 0.0
    assert _category(a, "Tasks")["category_score_100"] == 40.0  # (80 + 0) / 2, the zero counts


# -- attendance / participation ------------------------------------------


def test_attendance_summary(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)

    body = client.get(_url(seed["course_id"]), headers=admin_headers).json()

    assert _student_row(body, seed["a"])["attendance"] == {
        "closed_sessions": 4,
        "present_sessions": 3,
        "absent_sessions": 1,
        "score_100": 75.0,
    }
    # B's only record is in the OPEN session, which never counts: a real zero.
    assert _student_row(body, seed["b"])["attendance"] == {
        "closed_sessions": 4,
        "present_sessions": 0,
        "absent_sessions": 4,
        "score_100": 0.0,
    }


def test_participation_summary_and_student_without_observations(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)

    body = client.get(_url(seed["course_id"]), headers=admin_headers).json()

    assert _student_row(body, seed["a"])["participation"] == {
        "participation_count": 1,
        "participation_average": 2.0,
        "participation_score_100": 66.67,
    }
    assert _student_row(body, seed["b"])["participation"] == {
        "participation_count": 0,
        "participation_average": None,
        "participation_score_100": None,
    }


def test_attendance_participation_detail_shows_the_33_67_build_up(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)

    body = client.get(_url(seed["course_id"]), headers=admin_headers).json()
    detail = _student_row(body, seed["a"])["attendance_participation"]

    assert detail == {
        "attendance_score_100": 75.0,
        "attendance_weight_percent": 33.0,
        "attendance_contribution_points": 24.75,  # 75 * 0.33
        "participation_score_100": 66.67,
        "participation_weight_percent": 67.0,
        "participation_contribution_points": 44.67,  # 66.666... * 0.67
        "category_score_100": 69.42,  # 24.75 + 44.666...
        "category_weight_percent": 20.0,
        "category_contribution_points": 13.88,  # 69.4166... * 20 / 100
    }


def test_attendance_participation_category_is_null_when_participation_is_missing(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)

    body = client.get(_url(seed["course_id"]), headers=admin_headers).json()
    b = _student_row(body, seed["b"])
    detail = b["attendance_participation"]

    # Attendance exists (a real 0), participation doesn't: the category is NULL, not 0.
    assert detail["attendance_score_100"] == 0.0
    assert detail["attendance_contribution_points"] == 0.0
    assert detail["participation_score_100"] is None
    assert detail["participation_contribution_points"] is None
    assert detail["category_score_100"] is None
    assert detail["category_contribution_points"] is None
    ap = _category(b, "Attendance / Participation")
    assert ap["category_score_100"] is None and ap["contribution_points"] is None


def test_attendance_score_is_null_and_category_null_without_closed_sessions(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id = create_course(db_engine)
    _seed_scheme(db_engine, course_id)
    student_id = create_student(db_engine, account_number="8711")
    create_enrollment(db_engine, student_id=student_id, course_id=course_id)
    open_id = create_attendance_session(db_engine, course_id=course_id, opened_at=T0, status="OPEN")
    create_attendance_record(
        db_engine, attendance_session_id=open_id, student_id=student_id, recorded_at=T0
    )
    create_participation_observation(db_engine, course_id=course_id, student_id=student_id, value=3)

    student = client.get(_url(course_id), headers=admin_headers).json()["students"][0]

    assert student["attendance"] == {
        "closed_sessions": 0,
        "present_sessions": 0,
        "absent_sessions": 0,
        "score_100": None,
    }
    detail = student["attendance_participation"]
    assert detail["attendance_score_100"] is None
    assert detail["participation_score_100"] == 100.0
    assert detail["category_score_100"] is None
    assert detail["category_contribution_points"] is None


def test_course_without_an_attendance_participation_category_has_no_detail_block(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id = create_course(db_engine)
    student_id = create_student(db_engine, account_number="8721")
    create_enrollment(db_engine, student_id=student_id, course_id=course_id)
    item = create_grade_item(db_engine, course_id=course_id)
    category = create_grade_category(
        db_engine, course_id=course_id, name="Tasks", weight_percent=Decimal("100"), sort_order=1
    )
    assign_grade_item_to_category(db_engine, grade_item_id=item, category_id=category)
    create_student_grade(db_engine, grade_item_id=item, student_id=student_id, grade=Decimal("90"))

    student = client.get(_url(course_id), headers=admin_headers).json()["students"][0]

    assert student["attendance_participation"] is None
    assert student["current_score_100"] == 90.0
    assert student["attendance"]["score_100"] is None  # still reported, no sessions


# -- categories, overall, no final grade ---------------------------------


def test_category_contributions_and_overall_grade(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)

    body = client.get(_url(seed["course_id"]), headers=admin_headers).json()
    a = _student_row(body, seed["a"])

    tasks = _category(a, "Tasks")
    assert (tasks["category_score_100"], tasks["contribution_points"]) == (40.0, 16.0)
    assert tasks["calculation_type"] == "GRADE_ITEMS" and tasks["weight_percent"] == 40.0
    ap = _category(a, "Attendance / Participation")
    assert (ap["category_score_100"], ap["contribution_points"]) == (69.42, 13.88)
    assert ap["calculation_type"] == "ATTENDANCE_PARTICIPATION"
    exams = _category(a, "Exams")  # its only item is ungraded: excluded, never zero
    assert (exams["category_score_100"], exams["contribution_points"]) == (None, None)

    assert a["evaluated_weight_percent"] == 60.0  # Tasks 40 + A/P 20
    assert a["weighted_points_earned"] == 29.88  # 16 + 13.8833...
    assert a["current_score_100"] == 49.81  # 29.8833... / 60 * 100
    assert a["current_grade_10"] == 4.98


def test_student_with_nothing_evaluable_has_null_current_grade(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)

    b = _student_row(client.get(_url(seed["course_id"]), headers=admin_headers).json(), seed["b"])

    assert b["evaluated_weight_percent"] == 0.0
    assert b["weighted_points_earned"] == 0.0
    assert b["current_score_100"] is None
    assert b["current_grade_10"] is None


def test_no_final_grade_is_invented(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)

    body = client.get(_url(seed["course_id"]), headers=admin_headers).json()

    assert not [k for k in _all_keys(body) if "final" in k.lower()]
    assert {"current_score_100", "current_grade_10"} <= set(body["students"][0])


def test_course_with_no_students_or_items_returns_empty_structures(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id = create_course(db_engine, name="Empty")

    response = client.get(_url(course_id), headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {
        "course": {"course_id": course_id, "name": "Empty"},
        "scheme": [],
        "columns": [],
        "students": [],
    }


def test_unknown_course_returns_404(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get(_url(999_999), headers=admin_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Course not found"}


# -- consistency with the per-student evaluation --------------------------


def test_gradebook_numbers_match_the_per_student_evaluation(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)
    body = client.get(_url(seed["course_id"]), headers=admin_headers).json()

    for student_id in (seed["a"], seed["b"]):
        with Session(db_engine) as db:
            expected = evaluation_service.get_student_evaluation(db, student_id, seed["course_id"])
        row = _student_row(body, student_id)

        assert row["weighted_points_earned"] == expected.weighted_points_earned
        assert row["evaluated_weight_percent"] == expected.evaluated_weight_percent
        assert row["current_score_100"] == expected.current_score_100
        assert row["current_grade_10"] == expected.current_grade_10
        assert [
            (
                c["category_id"],
                c["name"],
                c["weight_percent"],
                c["category_score_100"],
                c["contribution_points"],
            )
            for c in row["categories"]
        ] == [
            (c.category_id, c.name, c.weight_percent, c.category_score_100, c.contribution_points)
            for c in expected.categories
        ]

        # ...and against the existing HTTP endpoint, whose shape is unchanged.
        http = client.get(
            f"/students/{student_id}/evaluation",
            params={"course_id": seed["course_id"]},
            headers=admin_headers,
        ).json()
        assert row["current_score_100"] == http["current_score_100"]
        assert row["current_grade_10"] == http["current_grade_10"]


# -- efficiency ---------------------------------------------------------


def _seed_large_class(db_engine: Engine, students: int) -> int:
    """A course with `students` enrolled students, 4 assigned items each
    graded, 6 closed sessions, and participation observations — inserted
    in bulk so seeding stays fast.
    """
    course_id = create_course(db_engine, name=f"Class of {students}")
    ids = _seed_scheme(db_engine, course_id)
    with db_engine.begin() as connection:
        student_ids = [
            connection.execute(
                insert(Student)
                .values(
                    account_number=f"9{students:03d}{n:04d}", first_name="S", last_name=f"N{n:04d}"
                )
                .returning(Student.id)
            ).scalar_one()
            for n in range(students)
        ]
        connection.execute(
            insert(Enrollment), [{"student_id": s, "course_id": course_id} for s in student_ids]
        )
        connection.execute(
            insert(StudentGrade),
            [
                {"grade_item_id": item, "student_id": s, "grade": Decimal(70 + i)}
                for s in student_ids
                for i, item in enumerate((ids["task1"], ids["task2"], ids["exam"]))
            ],
        )
        session_ids = [
            connection.execute(
                insert(AttendanceSession)
                .values(course_id=course_id, opened_at=T0 + timedelta(days=n), status="CLOSED")
                .returning(AttendanceSession.id)
            ).scalar_one()
            for n in range(6)
        ]
        connection.execute(
            insert(AttendanceRecord),
            [
                {"attendance_session_id": sid, "student_id": s, "recorded_at": T0}
                for s in student_ids
                for sid in session_ids[:5]
            ],
        )
        connection.execute(
            insert(ParticipationObservation),
            [
                {"course_id": course_id, "student_id": s, "value": v}
                for s in student_ids
                for v in (3, 2, 3)
            ],
        )
    return course_id


def _count_statements(engine: Engine, action: Any) -> int:
    statements: list[str] = []

    def _record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        action()
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return len(statements)


def test_query_count_does_not_grow_with_class_size(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    small_course = _seed_large_class(db_engine, 3)
    large_course = _seed_large_class(db_engine, 30)

    small = _count_statements(
        app_db_session.engine, lambda: client.get(_url(small_course), headers=admin_headers)
    )
    large = _count_statements(
        app_db_session.engine, lambda: client.get(_url(large_course), headers=admin_headers)
    )

    assert small == large
    assert large <= 12  # auth lookup + course + roster + categories + items + grades + 3 aggregates
    body = client.get(_url(large_course), headers=admin_headers).json()
    assert len(body["students"]) == 30
    assert all(
        s["attendance"]["score_100"] == pytest.approx(83.33, abs=0.01) for s in body["students"]
    )


def test_gradebook_never_evaluates_students_one_by_one(
    client: TestClient,
    db_engine: Engine,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = _seed_class(db_engine)

    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the gradebook must not load or evaluate per student")

    monkeypatch.setattr(evaluation_service, "get_student_evaluation", _forbidden)
    monkeypatch.setattr(evaluation_service, "_attendance_participation_score_100", _forbidden)
    monkeypatch.setattr(
        evaluation_service.repo, "list_evaluation_items_for_student_course", _forbidden
    )
    monkeypatch.setattr(
        evaluation_service.participation_repository, "list_observations", _forbidden
    )
    monkeypatch.setattr(evaluation_service, "get_attendance_score", _forbidden)

    response = client.get(_url(seed["course_id"]), headers=admin_headers)

    assert response.status_code == 200
    assert len(response.json()["students"]) == 2


# -- authorization ------------------------------------------------------


def test_student_key_gets_403(client: TestClient, db_engine: Engine) -> None:
    seed = _seed_class(db_engine)
    headers = {"X-API-Key": issue_test_student_key(db_engine, account_number="8701")}

    response = client.get(_url(seed["course_id"]), headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin API key required"}


def test_missing_invalid_and_revoked_keys_return_401(client: TestClient, db_engine: Engine) -> None:
    seed = _seed_class(db_engine)
    revoked = issue_test_admin_key(db_engine)
    revoke_test_key_by_plaintext(db_engine, revoked)

    for headers in ({}, {"X-API-Key": "bogus"}, {"X-API-Key": revoked}):
        assert client.get(_url(seed["course_id"]), headers=headers).status_code == 401


def test_gradebook_does_not_write(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    seed = _seed_class(db_engine)
    counts_before = _row_counts(db_engine)

    client.get(_url(seed["course_id"]), headers=admin_headers)
    client.get(f"/admin/courses/{seed['course_id']}/students", headers=admin_headers)

    assert _row_counts(db_engine) == counts_before


def _row_counts(engine: Engine) -> dict[str, int]:
    from sqlalchemy import func, select

    models = (
        Course,
        Student,
        Enrollment,
        GradeItem,
        GradeItemEvaluation,
        StudentGrade,
        AttendanceSession,
        AttendanceRecord,
        ParticipationObservation,
    )
    with engine.connect() as connection:
        return {
            m.__tablename__: connection.execute(select(func.count()).select_from(m)).scalar_one()
            for m in models
        }
