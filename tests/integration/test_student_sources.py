from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.academic.models import Student
from app.integration.models import StudentSource

NONEXISTENT_ID = 999_999


def _student(db_session: Session, account_number: str) -> Student:
    student = Student(account_number=account_number, first_name="A", last_name="B")
    db_session.add(student)
    db_session.commit()
    return student


def test_moodle_source_mapping_can_reference_a_student(db_session: Session) -> None:
    student = _student(db_session, "3001")

    mapping = StudentSource(student_id=student.id, source_system="moodle", source_id="137")
    db_session.add(mapping)
    db_session.commit()

    assert mapping.id is not None


def test_attendance_mapping_can_reference_the_same_canonical_student(db_session: Session) -> None:
    student = _student(db_session, "3002")

    db_session.add(StudentSource(student_id=student.id, source_system="moodle", source_id="138"))
    db_session.add(StudentSource(student_id=student.id, source_system="attendance", source_id="25"))
    db_session.commit()

    mappings = db_session.scalars(
        select(StudentSource).where(StudentSource.student_id == student.id)
    ).all()

    assert {m.source_system for m in mappings} == {"moodle", "attendance"}


def test_duplicate_source_system_and_id_fails(db_session: Session) -> None:
    student = _student(db_session, "3003")

    db_session.add(StudentSource(student_id=student.id, source_system="moodle", source_id="139"))
    db_session.commit()

    db_session.add(StudentSource(student_id=student.id, source_system="moodle", source_id="139"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_source_mapping_to_nonexistent_student_fails(db_session: Session) -> None:
    db_session.add(
        StudentSource(student_id=NONEXISTENT_ID, source_system="moodle", source_id="140")
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_last_seen_at_is_not_automatically_advanced_on_update(db_session: Session) -> None:
    """last_seen_at defaults on insert but is not auto-maintained on UPDATE
    (no `onupdate`). A future sync pass that re-observes this mapping must
    advance last_seen_at explicitly — see SourceMappingMixin.
    """
    student = _student(db_session, "3004")
    mapping = StudentSource(student_id=student.id, source_system="moodle", source_id="141")
    db_session.add(mapping)
    db_session.commit()
    original_last_seen_at = mapping.last_seen_at

    db_session.execute(
        update(StudentSource).where(StudentSource.id == mapping.id).values(source_hash="abc123")
    )
    db_session.commit()
    db_session.refresh(mapping)

    assert mapping.source_hash == "abc123"
    assert mapping.last_seen_at == original_last_seen_at


def test_last_seen_at_can_be_set_explicitly_on_update(db_session: Session) -> None:
    student = _student(db_session, "3005")
    mapping = StudentSource(student_id=student.id, source_system="moodle", source_id="142")
    db_session.add(mapping)
    db_session.commit()

    explicit_last_seen_at = datetime.now(UTC) + timedelta(days=1)
    db_session.execute(
        update(StudentSource)
        .where(StudentSource.id == mapping.id)
        .values(last_seen_at=explicit_last_seen_at)
    )
    db_session.commit()
    db_session.refresh(mapping)

    assert mapping.last_seen_at == explicit_last_seen_at
