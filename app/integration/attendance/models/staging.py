import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StagingAttendanceStudent(Base):
    """Normalized, structurally-valid candidate Attendance student for one batch.

    Rebuilt on every run (existing `source_system='attendance'` rows are
    replaced) — a scratch work area, not a system of record. Account
    number reconciliation against academic.students happens later, in
    validation — this table only proves the row is structurally sound.
    """

    __tablename__ = "attendance_students"
    __table_args__ = (
        UniqueConstraint(
            "source_system", "source_id", name="uq_staging_attendance_students_source"
        ),
        CheckConstraint(
            "length(trim(account_number)) > 0",
            name="ck_staging_attendance_students_account_number_not_empty",
        ),
        {"schema": "staging"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    account_number: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)


class StagingAttendanceSession(Base):
    """Normalized, structurally-valid candidate Attendance session for one batch."""

    __tablename__ = "attendance_sessions"
    __table_args__ = (
        UniqueConstraint(
            "source_system", "source_id", name="uq_staging_attendance_sessions_source"
        ),
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED')", name="ck_staging_attendance_sessions_status"
        ),
        {"schema": "staging"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)


class StagingAttendanceRecord(Base):
    """Normalized, structurally-valid candidate attendance record for one batch.

    student_source_id/session_source_id are validated against the
    batch's staged attendance students/sessions during
    validate_staged_batch, not by a DB foreign key.
    """

    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint(
            "source_system", "source_id", name="uq_staging_attendance_records_source"
        ),
        {"schema": "staging"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    student_source_id: Mapped[str] = mapped_column(Text, nullable=False)
    session_source_id: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
