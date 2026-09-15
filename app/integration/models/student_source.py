from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.integration.models.mixins import SourceMappingMixin


class StudentSource(SourceMappingMixin, Base):
    """Maps one canonical academic.students row to one source identity."""

    __tablename__ = "student_sources"
    __table_args__ = (
        UniqueConstraint("source_system", "source_id", name="uq_student_sources_source"),
        CheckConstraint(
            "length(trim(source_system)) > 0", name="ck_student_sources_source_system_not_empty"
        ),
        CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_student_sources_source_id_not_empty"
        ),
        Index("ix_student_sources_student_id", "student_id"),
        {"schema": "integration"},
    )

    student_id: Mapped[int] = mapped_column(
        ForeignKey("academic.students.id", ondelete="RESTRICT"), nullable=False
    )
