import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RawMoodleGradeItem(Base):
    """Landing copy of one Moodle grade item, as extracted for one batch.

    Extraction only ever selects itemtype='mod' rows (see
    app.integration.moodle.grades_source) — the course total
    (itemtype='course') and category totals never reach RAW. hidden is
    preserved faithfully here even though staging excludes hidden rows
    from ever becoming canonical — see the README's hidden-data section.
    """

    __tablename__ = "grade_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "source_id", name="uq_raw_moodle_grade_items_batch_source"),
        {"schema": "raw_moodle"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    course_source_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    itemmodule: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_grade: Mapped[Decimal | None] = mapped_column(Numeric(10, 5), nullable=True)
    hidden: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RawMoodleStudentGrade(Base):
    """Landing copy of one Moodle student grade (mdl_grade_grades row).

    student_source_id is the Moodle user id, stringified — the same
    identity space as integration.student_sources(source_system='moodle')
    — resolution against that mapping happens later, in the merge, never
    here. finalgrade is stored as-is: NULL stays NULL, never coerced to
    zero. Never rawgrade — see the README's grade semantics section.
    """

    __tablename__ = "student_grades"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "source_id", name="uq_raw_moodle_student_grades_batch_source"
        ),
        {"schema": "raw_moodle"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    grade_item_source_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    student_source_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    grade: Mapped[Decimal | None] = mapped_column(Numeric(10, 5), nullable=True)
    hidden: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
