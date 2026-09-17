from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: Allowed integration.sync_issues.status values.
SYNC_ISSUE_STATUSES = ("OPEN", "RESOLVED")
_status_check_sql = "status IN ({})".format(", ".join(f"'{s}'" for s in SYNC_ISSUE_STATUSES))


class SyncIssue(Base):
    """A generic, queryable record of a skipped inconsistency.

    Not tied to any one source_system or pipeline: any sync can use this
    to make something it deliberately chose not to treat as a batch-
    blocking failure stay visible and queryable, instead of disappearing
    into a rows_skipped counter. See app.integration.issues for the
    open/resolve helpers that write to this table, and
    app.integration.attendance.merge for the current caller (an
    Attendance student whose account_number doesn't resolve to any
    academic student yet).

    Rows are never deleted — a RESOLVED row is retained permanently as
    history. Identity is (source_system, issue_type, source_entity,
    source_id): reprocessing the same inconsistency on a later run must
    upsert the existing row, not insert a new one every time.
    first_seen_at/last_seen_at/resolved_at are always set explicitly by
    the writing code (see app.integration.issues) — never an ORM/Core
    `onupdate`, no triggers, per the platform's timestamp invariant.
    """

    __tablename__ = "sync_issues"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "issue_type",
            "source_entity",
            "source_id",
            name="uq_sync_issues_identity",
        ),
        CheckConstraint(_status_check_sql, name="ck_sync_issues_status"),
        CheckConstraint(
            "length(trim(source_system)) > 0", name="ck_sync_issues_source_system_not_empty"
        ),
        CheckConstraint(
            "length(trim(issue_type)) > 0", name="ck_sync_issues_issue_type_not_empty"
        ),
        CheckConstraint(
            "length(trim(source_entity)) > 0", name="ck_sync_issues_source_entity_not_empty"
        ),
        CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_sync_issues_source_id_not_empty"
        ),
        Index("ix_sync_issues_status", "status"),
        Index("ix_sync_issues_source_system", "source_system"),
        Index("ix_sync_issues_issue_type", "issue_type"),
        Index("ix_sync_issues_reference_value", "reference_value"),
        {"schema": "integration"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    issue_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_entity: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    reference_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
