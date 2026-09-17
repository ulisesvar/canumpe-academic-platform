import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StagingGradeItem(Base):
    """Normalized, structurally-valid candidate grade item for one batch.

    Rebuilt on every run (existing source_system='moodle' rows are
    replaced) — a scratch work area, not a system of record. Hidden
    items never reach here at all (excluded while staging is built) —
    see app.integration.moodle.grades_staging_writer.
    """

    __tablename__ = "grade_items"
    __table_args__ = (
        UniqueConstraint("source_system", "source_id", name="uq_staging_grade_items_source"),
        CheckConstraint("length(trim(name)) > 0", name="ck_staging_grade_items_name_not_empty"),
        CheckConstraint("max_grade > 0", name="ck_staging_grade_items_max_grade_positive"),
        {"schema": "staging"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    course_source_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    itemmodule: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_grade: Mapped[Decimal] = mapped_column(Numeric(10, 5), nullable=False)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)


class StagingStudentGrade(Base):
    """Normalized, structurally-valid candidate student grade for one batch.

    grade_item_source_id/student_source_id are validated against the
    batch's staged grade items during validate_staged_grades_batch, not
    by a DB foreign key. grade stays nullable all the way through — see
    the README's NULL-vs-zero grade semantics.
    """

    __tablename__ = "student_grades"
    __table_args__ = (
        UniqueConstraint("source_system", "source_id", name="uq_staging_student_grades_source"),
        {"schema": "staging"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    grade_item_source_id: Mapped[str] = mapped_column(Text, nullable=False)
    student_source_id: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[Decimal | None] = mapped_column(Numeric(10, 5), nullable=True)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
