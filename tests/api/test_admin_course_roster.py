"""HTTP-level tests for GET /admin/courses/{course_id}/students."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, update

from app.academic.models import Enrollment, Student
from tests.api.helpers import (
    create_course,
    create_enrollment,
    issue_test_admin_key,
    issue_test_student_key,
    revoke_test_key_by_plaintext,
)


def _student(db_engine: Engine, account_number: str, first_name: str, last_name: str) -> int:
    with db_engine.begin() as connection:
        return connection.execute(
            insert(Student)
            .values(account_number=account_number, first_name=first_name, last_name=last_name)
            .returning(Student.id)
        ).scalar_one()


def _url(course_id: int) -> str:
    return f"/admin/courses/{course_id}/students"


def test_roster_returns_all_of_the_courses_students(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id = create_course(db_engine)
    ids = [
        _student(db_engine, "8601", "Ana", "Zamora"),
        _student(db_engine, "8602", "Luis", "Alvarez"),
        _student(db_engine, "8603", "Bea", "Alvarez"),
    ]
    for student_id in ids:
        create_enrollment(db_engine, student_id=student_id, course_id=course_id)

    response = client.get(_url(course_id), headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["course_id"] == course_id
    assert {s["student_id"] for s in body["students"]} == set(ids)
    assert set(body["students"][0]) == {
        "student_id",
        "account_number",
        "first_name",
        "last_name",
        "full_name",
    }


def test_roster_is_ordered_by_last_name_then_first_name_then_id(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id = create_course(db_engine)
    for account, first, last in (
        ("8611", "Ana", "Zamora"),
        ("8612", "Luis", "Alvarez"),
        ("8613", "Bea", "Alvarez"),
    ):
        create_enrollment(
            db_engine, student_id=_student(db_engine, account, first, last), course_id=course_id
        )

    body = client.get(_url(course_id), headers=admin_headers).json()

    assert [s["full_name"] for s in body["students"]] == [
        "Bea Alvarez",
        "Luis Alvarez",
        "Ana Zamora",
    ]
    assert body == client.get(_url(course_id), headers=admin_headers).json()


def test_roster_excludes_students_from_other_courses(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id = create_course(db_engine)
    other_course_id = create_course(db_engine, name="Other")
    mine = _student(db_engine, "8621", "Mine", "Student")
    theirs = _student(db_engine, "8622", "Their", "Student")
    create_enrollment(db_engine, student_id=mine, course_id=course_id)
    create_enrollment(db_engine, student_id=theirs, course_id=other_course_id)

    body = client.get(_url(course_id), headers=admin_headers).json()

    assert [s["student_id"] for s in body["students"]] == [mine]


def test_full_name_is_derived_from_first_and_last_name(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id = create_course(db_engine)
    student_id = _student(db_engine, "8631", "María José", "Pérez Ruiz")
    create_enrollment(db_engine, student_id=student_id, course_id=course_id)

    student = client.get(_url(course_id), headers=admin_headers).json()["students"][0]

    assert student["first_name"] == "María José"
    assert student["last_name"] == "Pérez Ruiz"
    assert student["full_name"] == "María José Pérez Ruiz"
    assert student["account_number"] == "8631"


def test_roster_of_a_course_with_no_students_is_empty(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id = create_course(db_engine)

    response = client.get(_url(course_id), headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {"course_id": course_id, "students": []}


def test_roster_uses_the_active_flag_of_the_enrollment(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    """The roster follows canonical enrollment data: active=false rows
    are excluded. (Ingestion never sets active=false today — see the
    endpoint's description — so this only matters once something does.)
    """
    course_id = create_course(db_engine)
    active = _student(db_engine, "8641", "Active", "Student")
    inactive = _student(db_engine, "8642", "Inactive", "Student")
    create_enrollment(db_engine, student_id=active, course_id=course_id)
    create_enrollment(db_engine, student_id=inactive, course_id=course_id)
    with db_engine.begin() as connection:
        connection.execute(
            update(Enrollment).where(Enrollment.student_id == inactive).values(active=False)
        )

    body = client.get(_url(course_id), headers=admin_headers).json()

    assert [s["student_id"] for s in body["students"]] == [active]


def test_unknown_course_returns_404(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get(_url(999_999), headers=admin_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Course not found"}


def test_student_key_gets_403(client: TestClient, db_engine: Engine) -> None:
    course_id = create_course(db_engine)
    student_id = _student(db_engine, "8651", "A", "B")
    headers = {"X-API-Key": issue_test_student_key(db_engine, account_number="8651")}
    create_enrollment(db_engine, student_id=student_id, course_id=course_id)

    response = client.get(_url(course_id), headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin API key required"}


def test_missing_invalid_and_revoked_keys_return_401(client: TestClient, db_engine: Engine) -> None:
    course_id = create_course(db_engine)
    revoked = issue_test_admin_key(db_engine)
    revoke_test_key_by_plaintext(db_engine, revoked)

    for headers in ({}, {"X-API-Key": "bogus"}, {"X-API-Key": revoked}):
        assert client.get(_url(course_id), headers=headers).status_code == 401
