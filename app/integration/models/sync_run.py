import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: Allowed integration.sync_runs.status values. PARTIAL is intentionally not
#: a valid status: a batch either finishes SUCCESS or is FAILED.
SYNC_RUN_STATUSES = ("RUNNING", "SUCCESS", "FAILED")
_status_check_sql = "status IN ({})".format(", ".join(f"'{s}'" for s in SYNC_RUN_STATUSES))


class SyncRun(Base):
    """Record of one execution of a future extraction/sync pipeline.

    Row counters and error state make each batch observable and auditable
    without needing to inspect raw/staging tables directly.
    """

    __tablename__ = "sync_runs"
    __table_args__ = (
        CheckConstraint(_status_check_sql, name="ck_sync_runs_status"),
        CheckConstraint("rows_read >= 0", name="ck_sync_runs_rows_read_nonneg"),
        CheckConstraint("rows_valid >= 0", name="ck_sync_runs_rows_valid_nonneg"),
        CheckConstraint("rows_inserted >= 0", name="ck_sync_runs_rows_inserted_nonneg"),
        CheckConstraint("rows_updated >= 0", name="ck_sync_runs_rows_updated_nonneg"),
        CheckConstraint("rows_unchanged >= 0", name="ck_sync_runs_rows_unchanged_nonneg"),
        CheckConstraint("rows_skipped >= 0", name="ck_sync_runs_rows_skipped_nonneg"),
        CheckConstraint("error_count >= 0", name="ck_sync_runs_error_count_nonneg"),
        CheckConstraint(
            "length(trim(source_system)) > 0", name="ck_sync_runs_source_system_not_empty"
        ),
        CheckConstraint("length(trim(entity_type)) > 0", name="ck_sync_runs_entity_type_not_empty"),
        {"schema": "integration"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_valid: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_inserted: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    rows_updated: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    rows_unchanged: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    rows_skipped: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    watermark_start: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    watermark_end: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
