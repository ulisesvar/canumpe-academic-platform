from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class GradeItem(TimestampMixin, Base):
    """One canonical gradable activity (a Moodle 'mod' grade item).

    The Moodle course total (itemtype='course') and any category totals
    are never canonicalized — see app.integration.moodle.grades_source.
    activity_type is the Moodle itemmodule (e.g. 'assign'), kept only for
    traceability — never a full model of Moodle's gradebook.
    """

    __tablename__ = "grade_items"
    __table_args__ = (
        Index("ix_grade_items_course_id", "course_id"),
        {"schema": "academic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("academic.courses.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    max_grade: Mapped[Decimal] = mapped_column(Numeric(10, 5), nullable=False)
    activity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
