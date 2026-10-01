from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

CALCULATION_GRADE_ITEMS = "GRADE_ITEMS"
CALCULATION_ATTENDANCE_PARTICIPATION = "ATTENDANCE_PARTICIPATION"
CALCULATION_TYPES = (CALCULATION_GRADE_ITEMS, CALCULATION_ATTENDANCE_PARTICIPATION)


class GradeCategory(TimestampMixin, Base):
    """One evaluation category for a course (e.g. "Tareas", weight 30%).

    Academic-Platform-owned configuration — Moodle has no concept of
    this. A single row's weight_percent is bounded to [0, 100] here;
    the cross-row rule "a course's categories total exactly 100%"
    cannot be a single-row CHECK constraint and is enforced instead in
    app.services.evaluation_service before any write.

    calculation_type says how the category is scored: 'GRADE_ITEMS'
    (the Phase 7 equal-weight average of its assigned grade items — the
    default for every existing row) or 'ATTENDANCE_PARTICIPATION' (a
    weighted blend of the student's attendance and participation
    scores, no grade items). The strategy is never inferred from name;
    at most one ATTENDANCE_PARTICIPATION category exists per course.

    moodle_activity_type is the Moodle activity type (itemmodule, e.g.
    'assign' or 'quiz') whose grade items the Moodle sync assigns to this
    category automatically — see app.integration.moodle.grades_merge. NULL
    means no automatic mapping (e.g. the attendance/participation category,
    which never comes from Moodle). It is unique per course, so a Moodle
    activity type maps to at most one category; PostgreSQL allows several
    NULLs. It is never matched by category name or id.
    """

    __tablename__ = "grade_categories"
    __table_args__ = (
        CheckConstraint("weight_percent >= 0", name="ck_grade_categories_weight_percent_nonneg"),
        CheckConstraint("weight_percent <= 100", name="ck_grade_categories_weight_percent_max"),
        UniqueConstraint("course_id", "name", name="uq_grade_categories_course_name"),
        UniqueConstraint("course_id", "sort_order", name="uq_grade_categories_course_sort_order"),
        UniqueConstraint(
            "course_id",
            "moodle_activity_type",
            name="uq_grade_categories_course_moodle_activity_type",
        ),
        CheckConstraint(
            "calculation_type IN ('GRADE_ITEMS', 'ATTENDANCE_PARTICIPATION')",
            name="ck_grade_categories_calculation_type",
        ),
        Index("ix_grade_categories_course_id", "course_id"),
        Index(
            "uq_grade_categories_course_attendance_participation",
            "course_id",
            unique=True,
            postgresql_where=text("calculation_type = 'ATTENDANCE_PARTICIPATION'"),
        ),
        {"schema": "academic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("academic.courses.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    weight_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    calculation_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=CALCULATION_GRADE_ITEMS,
        server_default=CALCULATION_GRADE_ITEMS,
    )
    moodle_activity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
