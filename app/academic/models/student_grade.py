from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class StudentGrade(TimestampMixin, Base):
    """One student's grade on one canonical grade item.

    grade is nullable and that distinction is load-bearing: NULL means
    "not graded yet" (Moodle's finalgrade IS NULL); a real zero grade is
    stored as numeric 0. Never coerce one into the other — see
    app.integration.moodle.grades_source and the README's grade
    semantics section.
    """

    __tablename__ = "student_grades"
    __table_args__ = (
        UniqueConstraint("grade_item_id", "student_id", name="uq_student_grades_item_student"),
        Index("ix_student_grades_grade_item_id", "grade_item_id"),
        Index("ix_student_grades_student_id", "student_id"),
        {"schema": "academic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    grade_item_id: Mapped[int] = mapped_column(
        ForeignKey("academic.grade_items.id", ondelete="RESTRICT"), nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("academic.students.id", ondelete="RESTRICT"), nullable=False
    )
    grade: Mapped[Decimal | None] = mapped_column(Numeric(10, 5), nullable=True)
