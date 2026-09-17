from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.api.helpers import create_course, create_enrollment, create_student


def test_courses_endpoint_returns_enrolled_courses(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="6001")
    course_id = create_course(db_engine, name="Intro to Programming", active=True)
    create_enrollment(db_engine, student_id=student_id, course_id=course_id)

    response = client.get(f"/students/{student_id}/courses", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["student_id"] == student_id
    assert body["courses"] == [
        {"course_id": course_id, "name": "Intro to Programming", "active": True}
    ]


def test_unrelated_students_courses_are_not_returned(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_a = create_student(db_engine, account_number="6002")
    student_b = create_student(db_engine, account_number="6003")
    course_a = create_course(db_engine, name="Course A")
    course_b = create_course(db_engine, name="Course B")
    create_enrollment(db_engine, student_id=student_a, course_id=course_a)
    create_enrollment(db_engine, student_id=student_b, course_id=course_b)

    response = client.get(f"/students/{student_a}/courses", headers=admin_headers)

    course_ids = [c["course_id"] for c in response.json()["courses"]]
    assert course_ids == [course_a]
    assert course_b not in course_ids


def test_source_and_integration_fields_are_not_exposed(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="6004")
    course_id = create_course(db_engine)
    create_enrollment(db_engine, student_id=student_id, course_id=course_id)

    response = client.get(f"/students/{student_id}/courses", headers=admin_headers)

    course = response.json()["courses"][0]
    assert set(course.keys()) == {"course_id", "name", "active"}
    forbidden_substrings = ("source", "hash", "batch", "sync", "raw_")
    body_text = response.text.lower()
    for forbidden in forbidden_substrings:
        assert forbidden not in body_text


def test_courses_are_returned_in_deterministic_order(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="6005")
    course_ids = [create_course(db_engine, name=f"Course {i}") for i in range(5)]
    for course_id in reversed(course_ids):
        create_enrollment(db_engine, student_id=student_id, course_id=course_id)

    first = client.get(f"/students/{student_id}/courses", headers=admin_headers).json()
    second = client.get(f"/students/{student_id}/courses", headers=admin_headers).json()

    returned_ids = [c["course_id"] for c in first["courses"]]
    assert returned_ids == sorted(returned_ids)
    assert first == second


def test_courses_endpoint_returns_empty_list_for_student_with_no_enrollments(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="6006")

    response = client.get(f"/students/{student_id}/courses", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {"student_id": student_id, "courses": []}
