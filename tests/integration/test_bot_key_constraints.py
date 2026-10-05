"""Database-level guarantees for the 'bot' role (migration
0012_bot_api_key_role): each role carries exactly the identity columns it
may, enforced by CHECK constraints rather than application code alone.
"""

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.academic.models import Course, Student
from app.auth.api_keys import (
    CourseNotFoundError,
    get_active_key_by_hash,
    hash_key,
    issue_admin_key,
    issue_bot_key,
    issue_student_key,
    list_keys,
)
from app.auth.models import ROLE_ADMIN, ROLE_BOT, ROLE_STUDENT, ApiKey


def _course(db_session: Session) -> int:
    course = Course(name="Bot Course", active=True)
    db_session.add(course)
    db_session.commit()
    return course.id


def _student(db_session: Session, account_number: str) -> int:
    student = Student(account_number=account_number, first_name="T", last_name="S")
    db_session.add(student)
    db_session.commit()
    return student.id


def _raw_insert(db_session: Session, **values: object) -> None:
    base = {"key_hash": hash_key(str(values)), "key_prefix": "canumpe_x_", "label": None}
    db_session.execute(insert(ApiKey).values(**{**base, **values}))


def test_issue_bot_key_persists_role_course_and_only_a_hash(db_session: Session) -> None:
    course_id = _course(db_session)

    generated = issue_bot_key(db_session, course_id=course_id, label="telegram-bot")

    row = db_session.execute(select(ApiKey).where(ApiKey.id == generated.id)).scalar_one()
    assert row.role == ROLE_BOT
    assert row.course_id == course_id
    assert row.student_id is None
    assert row.key_hash == hash_key(generated.plaintext)
    assert generated.plaintext.startswith("canumpe_bot_")
    assert generated.plaintext not in {row.key_hash, row.key_prefix}
    assert get_active_key_by_hash(db_session, hash_key(generated.plaintext)) is not None


def test_a_bot_key_requires_an_existing_course(db_session: Session) -> None:
    before = db_session.execute(select(func.count()).select_from(ApiKey)).scalar_one()

    with pytest.raises(CourseNotFoundError):
        issue_bot_key(db_session, course_id=987654)

    after = db_session.execute(select(func.count()).select_from(ApiKey)).scalar_one()
    assert after == before


def test_database_rejects_a_bot_key_without_course_id(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        _raw_insert(db_session, role=ROLE_BOT, student_id=None, course_id=None)
    db_session.rollback()


def test_database_rejects_a_bot_key_with_a_student_id(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "90001")

    with pytest.raises(IntegrityError):
        _raw_insert(db_session, role=ROLE_BOT, student_id=student_id, course_id=course_id)
    db_session.rollback()


def test_database_rejects_a_bot_key_for_a_nonexistent_course(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        _raw_insert(db_session, role=ROLE_BOT, student_id=None, course_id=987654)
    db_session.rollback()


def test_database_rejects_course_id_on_student_and_admin_keys(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "90002")

    with pytest.raises(IntegrityError):
        _raw_insert(db_session, role=ROLE_STUDENT, student_id=student_id, course_id=course_id)
    db_session.rollback()
    with pytest.raises(IntegrityError):
        _raw_insert(db_session, role=ROLE_ADMIN, student_id=None, course_id=course_id)
    db_session.rollback()


def test_database_still_rejects_an_unknown_role(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        _raw_insert(db_session, role="superuser", student_id=None, course_id=None)
    db_session.rollback()


def test_student_and_admin_issuing_is_unchanged(db_session: Session) -> None:
    _student(db_session, "90003")

    student_key = issue_student_key(db_session, account_number="90003")
    admin_key = issue_admin_key(db_session)

    rows = {r.id: r for r in db_session.execute(select(ApiKey)).scalars()}
    assert rows[student_key.id].role == ROLE_STUDENT
    assert rows[student_key.id].course_id is None
    assert rows[student_key.id].student_id is not None
    assert rows[admin_key.id].role == ROLE_ADMIN
    assert rows[admin_key.id].course_id is None
    assert rows[admin_key.id].student_id is None


def test_list_keys_reports_the_bot_course_without_secrets(db_session: Session) -> None:
    course_id = _course(db_session)
    generated = issue_bot_key(db_session, course_id=course_id)

    summary = {s.id: s for s in list_keys(db_session)}[generated.id]

    assert summary.role == ROLE_BOT
    assert summary.course_id == course_id
    assert summary.student_id is None
    assert not hasattr(summary, "key_hash")
