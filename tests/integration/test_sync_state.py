from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integration.models import SyncState


def test_valid_sync_state_can_be_stored(db_session: Session) -> None:
    state = SyncState(source_system="moodle", entity_type="student", state={"cursor": 42})
    db_session.add(state)
    db_session.commit()

    assert state.id is not None


def test_jsonb_state_round_trips(db_session: Session) -> None:
    payload = {"since": "2026-09-01", "page": 3}
    state = SyncState(source_system="attendance", entity_type="enrollment", state=payload)
    db_session.add(state)
    db_session.commit()
    db_session.refresh(state)

    assert state.state == payload


def test_duplicate_source_system_and_entity_type_fails(db_session: Session) -> None:
    db_session.add(SyncState(source_system="moodle", entity_type="course", state={}))
    db_session.commit()

    db_session.add(SyncState(source_system="moodle", entity_type="course", state={}))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_updated_at_is_not_automatically_advanced_when_state_changes(db_session: Session) -> None:
    """The watermark advance must be explicit: updating `state` alone must
    not silently touch updated_at (no `onupdate`) — a future sync
    implementation has to set updated_at in the same write.
    """
    state = SyncState(source_system="moodle", entity_type="student", state={"cursor": 1})
    db_session.add(state)
    db_session.commit()
    original_updated_at = state.updated_at

    db_session.execute(
        update(SyncState).where(SyncState.id == state.id).values(state={"cursor": 2})
    )
    db_session.commit()
    db_session.refresh(state)

    assert state.state == {"cursor": 2}
    assert state.updated_at == original_updated_at


def test_updated_at_can_be_set_explicitly_when_advancing_the_watermark(
    db_session: Session,
) -> None:
    state = SyncState(source_system="moodle", entity_type="course", state={"cursor": 1})
    db_session.add(state)
    db_session.commit()

    explicit_updated_at = datetime.now(UTC) + timedelta(days=1)
    db_session.execute(
        update(SyncState)
        .where(SyncState.id == state.id)
        .values(state={"cursor": 2}, updated_at=explicit_updated_at)
    )
    db_session.commit()
    db_session.refresh(state)

    assert state.updated_at == explicit_updated_at
