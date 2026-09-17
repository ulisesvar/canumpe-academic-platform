"""Provisioning behavior (issue/rotate/revoke) at the function level —
see app.auth.api_keys. Uses the SAVEPOINT-rollback db_session fixture:
these functions call db.commit() internally, which the fixture is
explicitly designed to tolerate without ending the outer, rolled-back
transaction (see tests/conftest.py's db_session docstring).
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.academic.models import Student
from app.auth.api_keys import (
    ActiveStudentKeyExistsError,
    StudentNotFoundError,
    get_active_key_by_hash,
    hash_key,
    issue_admin_key,
    issue_student_key,
    list_keys,
    revoke_key,
    rotate_student_key,
)
from app.auth.models import ROLE_ADMIN, ROLE_STUDENT, ApiKey


def _student(db_session: Session, account_number: str) -> int:
    student = Student(account_number=account_number, first_name="Test", last_name="Student")
    db_session.add(student)
    db_session.commit()
    return student.id


def test_issuing_a_student_key_persists_only_the_hash_never_plaintext(
    db_session: Session,
) -> None:
    student_id = _student(db_session, "10001")

    generated = issue_student_key(db_session, account_number="10001")

    row = db_session.execute(select(ApiKey).where(ApiKey.id == generated.id)).scalar_one()
    assert row.key_hash == hash_key(generated.plaintext)
    assert row.key_hash != generated.plaintext
    assert row.student_id == student_id
    assert row.role == ROLE_STUDENT


def test_no_column_or_stored_value_equals_the_plaintext_key(db_session: Session) -> None:
    _student(db_session, "10002")
    generated = issue_student_key(db_session, account_number="10002")

    row = db_session.execute(select(ApiKey).where(ApiKey.id == generated.id)).scalar_one()
    stored_values = [row.key_hash, row.key_prefix]
    assert generated.plaintext not in stored_values


def test_issue_student_key_for_existing_student_succeeds(db_session: Session) -> None:
    student_id = _student(db_session, "10003")

    generated = issue_student_key(db_session, account_number="10003")

    assert generated.id is not None
    row = db_session.execute(select(ApiKey).where(ApiKey.id == generated.id)).scalar_one()
    assert row.student_id == student_id


def test_issue_student_key_for_nonexistent_account_number_fails(db_session: Session) -> None:
    with pytest.raises(StudentNotFoundError):
        issue_student_key(db_session, account_number="does-not-exist")


def test_second_active_student_key_is_prevented(db_session: Session) -> None:
    _student(db_session, "10004")
    issue_student_key(db_session, account_number="10004")

    with pytest.raises(ActiveStudentKeyExistsError):
        issue_student_key(db_session, account_number="10004")


def test_rotate_revokes_the_previous_active_key(db_session: Session) -> None:
    _student(db_session, "10005")
    original = issue_student_key(db_session, account_number="10005")

    rotate_student_key(db_session, account_number="10005")

    original_row = db_session.execute(
        select(ApiKey).where(ApiKey.id == original.id)
    ).scalar_one()
    assert original_row.revoked_at is not None


def test_rotate_creates_a_new_active_key(db_session: Session) -> None:
    _student(db_session, "10006")
    original = issue_student_key(db_session, account_number="10006")

    rotated = rotate_student_key(db_session, account_number="10006")

    assert rotated.id != original.id
    rotated_row = db_session.execute(select(ApiKey).where(ApiKey.id == rotated.id)).scalar_one()
    assert rotated_row.revoked_at is None


def test_previous_key_stops_authenticating_after_rotation(db_session: Session) -> None:
    _student(db_session, "10007")
    original = issue_student_key(db_session, account_number="10007")

    rotate_student_key(db_session, account_number="10007")

    assert get_active_key_by_hash(db_session, original.key_hash) is None


def test_new_key_authenticates_after_rotation(db_session: Session) -> None:
    _student(db_session, "10008")
    issue_student_key(db_session, account_number="10008")

    rotated = rotate_student_key(db_session, account_number="10008")

    found = get_active_key_by_hash(db_session, rotated.key_hash)
    assert found is not None
    assert found.id == rotated.id


def test_rotate_for_nonexistent_account_number_fails(db_session: Session) -> None:
    with pytest.raises(StudentNotFoundError):
        rotate_student_key(db_session, account_number="does-not-exist")


def test_admin_key_has_no_student_id(db_session: Session) -> None:
    generated = issue_admin_key(db_session, label="Test Admin")

    row = db_session.execute(select(ApiKey).where(ApiKey.id == generated.id)).scalar_one()
    assert row.student_id is None
    assert row.role == ROLE_ADMIN


def test_multiple_admin_keys_may_coexist(db_session: Session) -> None:
    first = issue_admin_key(db_session, label="Admin A")
    second = issue_admin_key(db_session, label="Admin B")

    assert first.id != second.id
    assert get_active_key_by_hash(db_session, first.key_hash) is not None
    assert get_active_key_by_hash(db_session, second.key_hash) is not None


def test_revoke_marks_the_key_revoked(db_session: Session) -> None:
    generated = issue_admin_key(db_session)

    revoke_key(db_session, api_key_id=generated.id)

    row = db_session.execute(select(ApiKey).where(ApiKey.id == generated.id)).scalar_one()
    assert row.revoked_at is not None


def test_revoked_key_no_longer_resolves_via_active_lookup(db_session: Session) -> None:
    generated = issue_admin_key(db_session)

    revoke_key(db_session, api_key_id=generated.id)

    assert get_active_key_by_hash(db_session, generated.key_hash) is None


def test_list_keys_reports_safe_metadata_including_account_number(db_session: Session) -> None:
    _student(db_session, "10009")
    student_key = issue_student_key(db_session, account_number="10009")
    admin_key = issue_admin_key(db_session, label="Ops")

    summaries = {summary.id: summary for summary in list_keys(db_session)}

    assert summaries[student_key.id].account_number == "10009"
    assert summaries[student_key.id].role == ROLE_STUDENT
    assert summaries[admin_key.id].account_number is None
    assert summaries[admin_key.id].label == "Ops"


def test_list_keys_never_exposes_plaintext_or_full_hash_fields(db_session: Session) -> None:
    _student(db_session, "10010")
    generated = issue_student_key(db_session, account_number="10010")

    summaries = list_keys(db_session)
    fields = {f for summary in summaries for f in vars(summary)}

    assert "key_hash" not in fields
    assert "plaintext" not in fields
    for summary in summaries:
        if summary.id == generated.id:
            assert generated.plaintext not in summary.key_prefix
