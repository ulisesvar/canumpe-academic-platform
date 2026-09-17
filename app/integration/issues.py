"""Generic operational issue tracking: integration.sync_issues.

Any pipeline can use this to make a deliberately-skipped inconsistency
observable and queryable instead of it disappearing into a rows_skipped
counter. Not specific to Attendance or any one source_system — see
app.integration.attendance.merge for the current caller (an Attendance
student whose account_number doesn't resolve to any academic student
yet, tracked as issue_type="UNRESOLVED_STUDENT").

Transaction boundary: both functions take an open `connection` and must
be called from inside the same transaction as the canonical merge that
discovers/resolves the issue (see sync.py's `with app_engine.begin()`
block around `merge_batch`). An OPEN issue row therefore only becomes
visible once that transaction actually commits, exactly like the
canonical writes and the sync_state watermark it sits alongside — if the
merge rolls back, the issue write rolls back with it. Per the platform's
timestamp invariant, first_seen_at/last_seen_at/resolved_at are always
passed in explicitly by the caller — never an ORM/Core `onupdate`, no
triggers.
"""

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from app.integration.models import SyncIssue
from app.integration.models.sync_issue import SYNC_ISSUE_STATUSES

OPEN, RESOLVED = SYNC_ISSUE_STATUSES


def open_issue(
    connection: Connection,
    *,
    source_system: str,
    issue_type: str,
    source_entity: str,
    source_id: str,
    reference_value: str | None,
    message: str,
    now: datetime,
) -> None:
    """Upserts one OPEN issue, keyed by (source_system, issue_type,
    source_entity, source_id). Reprocessing the same inconsistency every
    run (e.g. every 30 minutes) must not create a new row each time:
    first_seen_at is preserved by only ever being set on the initial
    INSERT; last_seen_at/reference_value/message are refreshed on every
    call via ON CONFLICT DO UPDATE. status/resolved_at are never touched
    here — only resolve_issue changes those.
    """
    stmt = pg_insert(SyncIssue).values(
        source_system=source_system,
        issue_type=issue_type,
        source_entity=source_entity,
        source_id=source_id,
        reference_value=reference_value,
        message=message,
        status=OPEN,
        first_seen_at=now,
        last_seen_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            SyncIssue.source_system,
            SyncIssue.issue_type,
            SyncIssue.source_entity,
            SyncIssue.source_id,
        ],
        set_={
            "reference_value": stmt.excluded.reference_value,
            "message": stmt.excluded.message,
            "last_seen_at": stmt.excluded.last_seen_at,
        },
    )
    connection.execute(stmt)


def resolve_issue(
    connection: Connection,
    *,
    source_system: str,
    issue_type: str,
    source_entity: str,
    source_id: str,
    now: datetime,
) -> None:
    """Marks the matching OPEN issue RESOLVED, if one exists — a no-op
    otherwise (e.g. a student that resolves on its very first sync,
    having never been unresolved). Never deletes the row: it is retained
    permanently as history.
    """
    connection.execute(
        update(SyncIssue)
        .where(
            SyncIssue.source_system == source_system,
            SyncIssue.issue_type == issue_type,
            SyncIssue.source_entity == source_entity,
            SyncIssue.source_id == source_id,
            SyncIssue.status == OPEN,
        )
        .values(status=RESOLVED, resolved_at=now, last_seen_at=now)
    )
