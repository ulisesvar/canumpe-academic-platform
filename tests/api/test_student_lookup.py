"""Student-existence semantics shared by every admin endpoint: unknown
student_id -> 404 with a consistent body; a real student with no related
data -> 200 with empty/zeroed data, never an error. All requests use an
ADMIN key — see tests/api/test_students_authorization.py for the
STUDENT-key-gets-403 behavior itself.
"""

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.api.helpers import create_student

UNKNOWN_STUDENT_ID = 999_999


def test_existing_student_resolves(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="5001")

    response = client.get(f"/students/{student_id}/summary", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["student_id"] == student_id


def test_unknown_student_returns_404(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get(f"/students/{UNKNOWN_STUDENT_ID}/summary", headers=admin_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Student not found"}


def test_unknown_student_returns_404_on_every_endpoint(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    for path in ("courses", "attendance", "grades", "summary"):
        response = client.get(f"/students/{UNKNOWN_STUDENT_ID}/{path}", headers=admin_headers)
        assert response.status_code == 404, f"expected 404 for /{path}"
        assert response.json() == {"detail": "Student not found"}


def test_valid_student_with_no_related_data_returns_200_not_an_error(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    student_id = create_student(db_engine, account_number="5002")

    for path in ("courses", "attendance", "grades", "summary"):
        response = client.get(f"/students/{student_id}/{path}", headers=admin_headers)
        assert response.status_code == 200, f"expected 200 for /{path}"
