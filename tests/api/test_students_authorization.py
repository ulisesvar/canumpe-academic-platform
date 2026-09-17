"""Role authorization: a STUDENT key may only ever use /me/*; an ADMIN
key may only ever use /students/{student_id}/* — see
app.auth.dependencies.require_admin / require_student.
"""

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.api.helpers import create_student, issue_test_admin_key, issue_test_student_key


def test_student_key_on_students_route_returns_403(client: TestClient, db_engine: Engine) -> None:
    create_student(db_engine, account_number="40001")
    key = issue_test_student_key(db_engine, account_number="40001")

    response = client.get("/students/1/courses", headers={"X-API-Key": key})

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin API key required"}


def test_student_key_on_every_students_route_returns_403(
    client: TestClient, db_engine: Engine
) -> None:
    create_student(db_engine, account_number="40002")
    key = issue_test_student_key(db_engine, account_number="40002")

    for path in ("courses", "attendance", "grades", "summary"):
        response = client.get(f"/students/1/{path}", headers={"X-API-Key": key})
        assert response.status_code == 403, f"expected 403 for /students/1/{path}"


def test_admin_key_on_students_route_succeeds(client: TestClient, db_engine: Engine) -> None:
    student_id = create_student(db_engine, account_number="40003")
    key = issue_test_admin_key(db_engine)

    response = client.get(f"/students/{student_id}/courses", headers={"X-API-Key": key})

    assert response.status_code == 200


def test_admin_key_on_me_route_returns_403(client: TestClient, db_engine: Engine) -> None:
    key = issue_test_admin_key(db_engine)

    response = client.get("/me", headers={"X-API-Key": key})

    assert response.status_code == 403
    assert response.json() == {"detail": "Student API key required"}


def test_admin_key_on_every_me_route_returns_403(client: TestClient, db_engine: Engine) -> None:
    key = issue_test_admin_key(db_engine)

    for path in ("", "/courses", "/attendance", "/grades", "/summary"):
        response = client.get(f"/me{path}", headers={"X-API-Key": key})
        assert response.status_code == 403, f"expected 403 for /me{path}"


def test_admin_key_against_unknown_student_returns_404(
    client: TestClient, db_engine: Engine
) -> None:
    key = issue_test_admin_key(db_engine)

    response = client.get("/students/999999/summary", headers={"X-API-Key": key})

    assert response.status_code == 404
    assert response.json() == {"detail": "Student not found"}
