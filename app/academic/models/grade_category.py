from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class GradeCategory(TimestampMixin, Base):
    """One evaluation category for a course (e.g. "Tareas", weight 30%).

    Academic-Platform-owned configuration — Moodle has no concept of
    this. A single row's weight_percent is bounded to [0, 100] here;
    the cross-row rule "a course's categories total exactly 100%"
    cannot be a single-row CHECK constraint and is enforced instead in
    app.services.evaluation_service before any write.
    """

    __tablename__ = "grade_categories"
    __table_args__ = (
        CheckConstraint("weight_percent >= 0", name="ck_grade_categories_weight_percent_nonneg"),
        CheckConstraint("weight_percent <= 100", name="ck_grade_categories_weight_percent_max"),
        UniqueConstraint("course_id", "name", name="uq_grade_categories_course_name"),
        UniqueConstraint("course_id", "sort_order", name="uq_grade_categories_course_sort_order"),
        Index("ix_grade_categories_course_id", "course_id"),
        {"schema": "academic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("academic.courses.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    weight_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
