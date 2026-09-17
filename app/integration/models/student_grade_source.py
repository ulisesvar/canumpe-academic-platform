from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.integration.models.mixins import SourceMappingMixin


class StudentGradeSource(SourceMappingMixin, Base):
    """Maps one canonical academic.student_grades row to one source identity."""

    __tablename__ = "student_grade_sources"
    __table_args__ = (
        UniqueConstraint("source_system", "source_id", name="uq_student_grade_sources_source"),
        CheckConstraint(
            "length(trim(source_system)) > 0",
            name="ck_student_grade_sources_source_system_not_empty",
        ),
        CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_student_grade_sources_source_id_not_empty"
        ),
        Index("ix_student_grade_sources_student_grade_id", "student_grade_id"),
        {"schema": "integration"},
    )

    student_grade_id: Mapped[int] = mapped_column(
        ForeignKey("academic.student_grades.id", ondelete="RESTRICT"), nullable=False
    )
