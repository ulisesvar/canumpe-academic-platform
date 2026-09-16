import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RawMoodleStudent(Base):
    """Landing copy of one Moodle-side student, as extracted for one batch.

    RAW is a faithful, append-only record of what extraction observed —
    not normalized, not validated, not a system of record. One row per
    (batch_id, source_id); reprocessing the same batch cannot duplicate
    rows because of the unique constraint below.
    """

    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("batch_id", "source_id", name="uq_raw_moodle_students_batch_source"),
        {"schema": "raw_moodle"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    account_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RawMoodleCourse(Base):
    """Landing copy of one Moodle-side course, as extracted for one batch."""

    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("batch_id", "source_id", name="uq_raw_moodle_courses_batch_source"),
        {"schema": "raw_moodle"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    visible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RawMoodleEnrollment(Base):
    """Landing copy of one Moodle-side enrollment, as extracted for one batch.

    source_id is Moodle's `mdl_user_enrolments.id` — stable and unique by
    construction (it is that table's primary key), which also naturally
    handles a student being enrolled in the same course via more than one
    enrolment method (each gets its own row here).
    """

    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("batch_id", "source_id", name="uq_raw_moodle_enrollments_batch_source"),
        CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_raw_moodle_enrollments_source_id_not_empty"
        ),
        {"schema": "raw_moodle"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    student_source_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    course_source_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
