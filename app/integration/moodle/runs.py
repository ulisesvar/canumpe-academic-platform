"""integration.sync_runs / integration.sync_state bookkeeping.

start_sync_run and mark_sync_run_failed each open their own short
transaction against `engine` — sync run bookkeeping is intentionally
outside the academic transaction's atomicity boundary, so a RUNNING row
can always be flipped to FAILED even when the failure happened before or
after the academic transaction ran. mark_sync_run_success and
advance_sync_state instead take an open `connection` and must be called
from inside the same transaction as the canonical merge, so that a
SUCCESS status and an advanced watermark are only ever visible once that
transaction actually commits.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine

from app.integration.models import SyncRun, SyncState
from app.integration.moodle.merge import MergeCounters


def start_sync_run(
    engine: Engine, batch_id: uuid.UUID, source_system: str, entity_type: str
) -> int:
    with engine.begin() as connection:
        return connection.execute(
            insert(SyncRun)
            .values(
                batch_id=batch_id,
                source_system=source_system,
                entity_type=entity_type,
                status="RUNNING",
            )
            .returning(SyncRun.id)
        ).scalar_one()


def mark_sync_run_failed(
    engine: Engine, run_id: int, *, error_message: str, rows_read: int, error_count: int = 1
) -> None:
    with engine.begin() as connection:
        connection.execute(
            update(SyncRun)
            .where(SyncRun.id == run_id)
            .values(
                status="FAILED",
                error_message=error_message,
                rows_read=rows_read,
                error_count=error_count,
                completed_at=datetime.now(UTC),
            )
        )


def mark_sync_run_success(
    connection: Connection,
    run_id: int,
    *,
    snapshot_time: datetime,
    rows_read: int,
    rows_valid: int,
    counters: MergeCounters,
) -> None:
    connection.execute(
        update(SyncRun)
        .where(SyncRun.id == run_id)
        .values(
            status="SUCCESS",
            snapshot_time=snapshot_time,
            rows_read=rows_read,
            rows_valid=rows_valid,
            rows_inserted=counters.rows_inserted,
            rows_updated=counters.rows_updated,
            rows_unchanged=counters.rows_unchanged,
            completed_at=datetime.now(UTC),
        )
    )


def advance_sync_state(
    connection: Connection,
    source_system: str,
    entity_type: str,
    state: dict[str, Any],
    updated_at: datetime,
) -> None:
    """Upsert the watermark. Only ever call this from the merge transaction,
    after the merge itself, so it commits (or not) atomically with it —
    never advanced before the academic merge has succeeded.
    """
    stmt = pg_insert(SyncState).values(
        source_system=source_system, entity_type=entity_type, state=state, updated_at=updated_at
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[SyncState.source_system, SyncState.entity_type],
        set_={"state": stmt.excluded.state, "updated_at": stmt.excluded.updated_at},
    )
    connection.execute(stmt)
