import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StagingStudent(Base):
    """Normalized, structurally-valid candidate student for one batch.

    Staging is a scratch work area, not a system of record: it is fully
    rebuilt (existing rows for a source_system are replaced) on every
    sync run and holds only the latest attempted batch — see the README
    for the staging lifecycle/cleanup strategy. A row only reaches here
    once it has passed row-level checks (present, non-empty account
    number); batch-level checks (duplicates, dangling references) are
    evaluated by reading this table back, not by constraints on it.
    """

    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("source_system", "source_id", name="uq_staging_students_source"),
        CheckConstraint(
            "length(trim(account_number)) > 0", name="ck_staging_students_account_number_not_empty"
        ),
        {"schema": "staging"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    account_number: Mapped[str] = mapped_column(Text, nullable=False)
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)


class StagingCourse(Base):
    """Normalized, structurally-valid candidate course for one batch."""

    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("source_system", "source_id", name="uq_staging_courses_source"),
        CheckConstraint("length(trim(name)) > 0", name="ck_staging_courses_name_not_empty"),
        {"schema": "staging"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)


class StagingEnrollment(Base):
    """Normalized, structurally-valid candidate enrollment for one batch.

    student_source_id/course_source_id are validated against the batch's
    staged students/courses during the separate validate_staged_batch
    pass, not by a DB foreign key — staging rows for one entity type are
    written independently and a partially-written batch must still be
    inspectable.
    """

    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("source_system", "source_id", name="uq_staging_enrollments_source"),
        {"schema": "staging"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    student_source_id: Mapped[str] = mapped_column(Text, nullable=False)
    course_source_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
