"""HTTP-level authentication semantics — see app.auth.dependencies.
Missing, malformed, unknown, and revoked keys all produce the exact
same generic 401 so a caller can never learn whether a key exists.
"""

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.api.helpers import (
    create_student,
    issue_test_admin_key,
    issue_test_student_key,
    revoke_test_key_by_plaintext,
)

_GENERIC_401_BODY = {"detail": "Invalid or missing API key"}


def test_missing_key_returns_401(client: TestClient) -> None:
    response = client.get("/me")

    assert response.status_code == 401
    assert response.json() == _GENERIC_401_BODY


def test_unknown_key_returns_401(client: TestClient) -> None:
    response = client.get("/me", headers={"X-API-Key": "canumpe_stu_" + "a" * 43})

    assert response.status_code == 401
    assert response.json() == _GENERIC_401_BODY


def test_malformed_key_returns_401(client: TestClient) -> None:
    response = client.get("/me", headers={"X-API-Key": "not-a-real-key-format"})

    assert response.status_code == 401
    assert response.json() == _GENERIC_401_BODY


def test_revoked_student_key_returns_401(client: TestClient, db_engine: Engine) -> None:
    create_student(db_engine, account_number="20001")
    key = issue_test_student_key(db_engine, account_number="20001")
    revoke_test_key_by_plaintext(db_engine, key)

    response = client.get("/me", headers={"X-API-Key": key})

    assert response.status_code == 401
    assert response.json() == _GENERIC_401_BODY


def test_revoked_admin_key_returns_401(client: TestClient, db_engine: Engine) -> None:
    key = issue_test_admin_key(db_engine)
    revoke_test_key_by_plaintext(db_engine, key)

    response = client.get("/students/1/summary", headers={"X-API-Key": key})

    assert response.status_code == 401
    assert response.json() == _GENERIC_401_BODY


def test_active_valid_student_key_authenticates(client: TestClient, db_engine: Engine) -> None:
    create_student(db_engine, account_number="20002")
    key = issue_test_student_key(db_engine, account_number="20002")

    response = client.get("/me", headers={"X-API-Key": key})

    assert response.status_code == 200


def test_active_valid_admin_key_authenticates(client: TestClient, db_engine: Engine) -> None:
    student_id = create_student(db_engine, account_number="20003")
    key = issue_test_admin_key(db_engine)

    response = client.get(f"/students/{student_id}/summary", headers={"X-API-Key": key})

    assert response.status_code == 200


def test_authentication_failures_never_echo_the_submitted_key(client: TestClient) -> None:
    distinctive_key = "canumpe_stu_THIS-EXACT-VALUE-MUST-NEVER-APPEAR-IN-A-RESPONSE"

    response = client.get("/me", headers={"X-API-Key": distinctive_key})

    assert distinctive_key not in response.text


def test_401_response_never_exposes_a_key_hash(client: TestClient, db_engine: Engine) -> None:
    create_student(db_engine, account_number="20004")
    key = issue_test_student_key(db_engine, account_number="20004")
    revoke_test_key_by_plaintext(db_engine, key)

    response = client.get("/me", headers={"X-API-Key": key})

    assert "key_hash" not in response.text
