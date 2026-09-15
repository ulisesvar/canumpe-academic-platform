from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.academic.models import Student


def test_valid_student_can_be_inserted(db_session: Session) -> None:
    student = Student(account_number="1001", first_name="Ada", last_name="Lovelace")
    db_session.add(student)
    db_session.commit()

    assert student.id is not None


def test_account_number_is_required(db_session: Session) -> None:
    db_session.add(Student(first_name="Ada", last_name="Lovelace"))

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_account_number_is_unique(db_session: Session) -> None:
    db_session.add(Student(account_number="1002", first_name="Ada", last_name="Lovelace"))
    db_session.commit()

    db_session.add(Student(account_number="1002", first_name="Grace", last_name="Hopper"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_account_number_behaves_as_text(db_session: Session) -> None:
    student = Student(account_number="000123", first_name="Ada", last_name="Lovelace")
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)

    assert student.account_number == "000123"


def test_email_can_be_duplicated(db_session: Session) -> None:
    db_session.add(
        Student(account_number="1003", first_name="A", last_name="B", email="shared@example.com")
    )
    db_session.add(
        Student(account_number="1004", first_name="C", last_name="D", email="shared@example.com")
    )

    db_session.commit()


def test_active_defaults_to_true(db_session: Session) -> None:
    student = Student(account_number="1005", first_name="A", last_name="B")
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)

    assert student.active is True


def test_updated_at_is_not_automatically_advanced_on_update(db_session: Session) -> None:
    """updated_at gets a DB default on insert, but nothing in the schema or
    the ORM mapping advances it on UPDATE. Pipeline writes (bulk updates,
    Core statements, upserts) must set it explicitly — see TimestampMixin.
    """
    student = Student(account_number="1006", first_name="A", last_name="B")
    db_session.add(student)
    db_session.commit()
    original_updated_at = student.updated_at

    db_session.execute(
        update(Student).where(Student.id == student.id).values(first_name="Changed")
    )
    db_session.commit()
    db_session.refresh(student)

    assert student.first_name == "Changed"
    assert student.updated_at == original_updated_at


def test_updated_at_can_be_set_explicitly_on_update(db_session: Session) -> None:
    """Write/sync code is expected to set updated_at itself, as this does."""
    student = Student(account_number="1007", first_name="A", last_name="B")
    db_session.add(student)
    db_session.commit()

    explicit_updated_at = datetime.now(UTC) + timedelta(days=1)
    db_session.execute(
        update(Student)
        .where(Student.id == student.id)
        .values(first_name="Changed", updated_at=explicit_updated_at)
    )
    db_session.commit()
    db_session.refresh(student)

    assert student.updated_at == explicit_updated_at
