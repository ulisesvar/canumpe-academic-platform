import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integration.models import SyncRun


def test_running_sync_run_can_be_recorded(db_session: Session) -> None:
    run = SyncRun(
        batch_id=uuid.uuid4(), source_system="moodle", entity_type="student", status="RUNNING"
    )
    db_session.add(run)
    db_session.commit()

    assert run.id is not None


def test_success_sync_run_can_be_recorded(db_session: Session) -> None:
    run = SyncRun(
        batch_id=uuid.uuid4(), source_system="moodle", entity_type="student", status="SUCCESS"
    )
    db_session.add(run)
    db_session.commit()

    assert run.status == "SUCCESS"


def test_failed_sync_run_can_be_recorded(db_session: Session) -> None:
    run = SyncRun(
        batch_id=uuid.uuid4(),
        source_system="moodle",
        entity_type="student",
        status="FAILED",
        error_message="boom",
    )
    db_session.add(run)
    db_session.commit()

    assert run.status == "FAILED"


def test_invalid_status_fails(db_session: Session) -> None:
    db_session.add(
        SyncRun(
            batch_id=uuid.uuid4(), source_system="moodle", entity_type="student", status="PARTIAL"
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_row_counters_default_to_zero(db_session: Session) -> None:
    run = SyncRun(
        batch_id=uuid.uuid4(), source_system="moodle", entity_type="student", status="RUNNING"
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    assert run.rows_read == 0
    assert run.rows_valid == 0
    assert run.rows_inserted == 0
    assert run.rows_updated == 0
    assert run.rows_unchanged == 0
    assert run.rows_skipped == 0
    assert run.error_count == 0


def test_negative_counters_fail(db_session: Session) -> None:
    db_session.add(
        SyncRun(
            batch_id=uuid.uuid4(),
            source_system="moodle",
            entity_type="student",
            status="RUNNING",
            rows_read=-1,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_batch_id_is_unique(db_session: Session) -> None:
    batch_id = uuid.uuid4()
    db_session.add(
        SyncRun(batch_id=batch_id, source_system="moodle", entity_type="student", status="RUNNING")
    )
    db_session.commit()

    db_session.add(
        SyncRun(batch_id=batch_id, source_system="moodle", entity_type="course", status="RUNNING")
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
