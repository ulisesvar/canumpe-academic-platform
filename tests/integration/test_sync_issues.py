"""integration.sync_issues lifecycle: app.integration.issues.open_issue/
resolve_issue, tested directly against the generic mechanism.

Attendance's specific use of this (the UNRESOLVED_STUDENT issue raised by
app.integration.attendance.merge) is covered end-to-end in
tests/integration/attendance/test_sync_issues.py. The full
OPEN -> RESOLVED -> OPEN (reopen) -> RESOLVED cycle exercised here isn't
reachable through the current Attendance pipeline (once a student's
mapping is created, that reconciliation path is never revisited), but
the generic mechanism must still support it correctly for any future
caller — hence testing it directly here.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integration.issues import open_issue, resolve_issue
from app.integration.models import SyncIssue

IDENTITY = {
    "source_system": "attendance",
    "issue_type": "UNRESOLVED_STUDENT",
    "source_entity": "student",
    "source_id": "7",
}
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _get(db_session: Session) -> SyncIssue:
    return db_session.execute(
        select(SyncIssue).where(
            SyncIssue.source_system == IDENTITY["source_system"],
            SyncIssue.issue_type == IDENTITY["issue_type"],
            SyncIssue.source_entity == IDENTITY["source_entity"],
            SyncIssue.source_id == IDENTITY["source_id"],
        )
    ).scalar_one()


def _all_for_identity(db_session: Session) -> list[SyncIssue]:
    return list(
        db_session.execute(
            select(SyncIssue).where(SyncIssue.source_id == IDENTITY["source_id"])
        ).scalars()
    )


def test_open_creates_one_open_issue(db_session: Session) -> None:
    open_issue(
        db_session.connection(),
        reference_value="321167907",
        message="does not resolve to any academic student yet",
        now=T0,
        **IDENTITY,
    )
    db_session.commit()

    issue = _get(db_session)
    assert issue.status == "OPEN"
    assert issue.first_seen_at == T0
    assert issue.last_seen_at == T0
    assert issue.resolved_at is None
    assert issue.reference_value == "321167907"


def test_resolve_marks_resolved_and_sets_resolved_at(db_session: Session) -> None:
    open_issue(
        db_session.connection(),
        reference_value="321167907",
        message="unresolved",
        now=T0,
        **IDENTITY,
    )
    db_session.commit()

    resolved_at = T0 + timedelta(minutes=30)
    resolve_issue(db_session.connection(), now=resolved_at, **IDENTITY)
    db_session.commit()

    issue = _get(db_session)
    assert issue.status == "RESOLVED"
    assert issue.resolved_at == resolved_at


def test_reopen_after_resolution_reuses_the_same_row(db_session: Session) -> None:
    open_issue(
        db_session.connection(),
        reference_value="321167907",
        message="unresolved",
        now=T0,
        **IDENTITY,
    )
    db_session.commit()
    original_id = _get(db_session).id

    resolved_at = T0 + timedelta(minutes=30)
    resolve_issue(db_session.connection(), now=resolved_at, **IDENTITY)
    db_session.commit()
    assert _get(db_session).status == "RESOLVED"

    reopened_at = resolved_at + timedelta(minutes=30)
    open_issue(
        db_session.connection(),
        reference_value="321167907",
        message="unresolved again",
        now=reopened_at,
        **IDENTITY,
    )
    db_session.commit()

    reopened = _get(db_session)
    # 3. same row.
    assert reopened.id == original_id
    # 4. status OPEN again.
    assert reopened.status == "OPEN"
    # 5. resolved_at cleared.
    assert reopened.resolved_at is None
    # 9. no duplicate row for this identity.
    assert len(_all_for_identity(db_session)) == 1


def test_first_seen_at_unchanged_across_the_full_open_resolve_reopen_cycle(
    db_session: Session,
) -> None:
    open_issue(
        db_session.connection(),
        reference_value="321167907",
        message="unresolved",
        now=T0,
        **IDENTITY,
    )
    db_session.commit()

    resolved_at = T0 + timedelta(minutes=30)
    resolve_issue(db_session.connection(), now=resolved_at, **IDENTITY)
    db_session.commit()

    reopened_at = resolved_at + timedelta(minutes=30)
    open_issue(
        db_session.connection(),
        reference_value="321167907",
        message="unresolved again",
        now=reopened_at,
        **IDENTITY,
    )
    db_session.commit()

    assert _get(db_session).first_seen_at == T0


def test_last_seen_at_advances_on_reopen(db_session: Session) -> None:
    open_issue(
        db_session.connection(),
        reference_value="321167907",
        message="unresolved",
        now=T0,
        **IDENTITY,
    )
    db_session.commit()

    resolved_at = T0 + timedelta(minutes=30)
    resolve_issue(db_session.connection(), now=resolved_at, **IDENTITY)
    db_session.commit()
    last_seen_at_when_resolved = _get(db_session).last_seen_at

    reopened_at = resolved_at + timedelta(minutes=30)
    open_issue(
        db_session.connection(),
        reference_value="321167907",
        message="unresolved again",
        now=reopened_at,
        **IDENTITY,
    )
    db_session.commit()

    assert _get(db_session).last_seen_at == reopened_at
    assert _get(db_session).last_seen_at > last_seen_at_when_resolved


def test_resolve_works_again_after_a_reopen(db_session: Session) -> None:
    open_issue(
        db_session.connection(),
        reference_value="321167907",
        message="unresolved",
        now=T0,
        **IDENTITY,
    )
    db_session.commit()
    first_resolved_at = T0 + timedelta(minutes=30)
    resolve_issue(db_session.connection(), now=first_resolved_at, **IDENTITY)
    db_session.commit()

    reopened_at = first_resolved_at + timedelta(minutes=30)
    open_issue(
        db_session.connection(),
        reference_value="321167907",
        message="unresolved again",
        now=reopened_at,
        **IDENTITY,
    )
    db_session.commit()
    original_id = _get(db_session).id

    second_resolved_at = reopened_at + timedelta(minutes=30)
    resolve_issue(db_session.connection(), now=second_resolved_at, **IDENTITY)
    db_session.commit()

    issue = _get(db_session)
    assert issue.id == original_id
    assert issue.status == "RESOLVED"
    assert issue.resolved_at == second_resolved_at
    assert issue.first_seen_at == T0
    assert len(_all_for_identity(db_session)) == 1
