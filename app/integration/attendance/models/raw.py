import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RawAttendanceStudent(Base):
    """Landing copy of one Attendance-side student, as extracted for one batch.

    Only account_number is kept — never telegram_id/telegram_username
    (see the README's minimal-data principle). RAW is a faithful,
    append-only record of what extraction observed — not validated, not
    reconciled, not a system of record.
    """

    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("batch_id", "source_id", name="uq_raw_attendance_students_batch_source"),
        {"schema": "raw_attendance"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    account_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RawAttendanceSession(Base):
    """Landing copy of one Attendance-side session, as extracted for one batch."""

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("batch_id", "source_id", name="uq_raw_attendance_sessions_batch_source"),
        {"schema": "raw_attendance"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RawAttendanceRecord(Base):
    """Landing copy of one Attendance-side attendance record for one batch.

    Never latitude/longitude/distance_meters — those are never ingested
    at all, at any pipeline stage.
    """

    __tablename__ = "attendances"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "source_id", name="uq_raw_attendance_attendances_batch_source"
        ),
        {"schema": "raw_attendance"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    student_source_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_source_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
