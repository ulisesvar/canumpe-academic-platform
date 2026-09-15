from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.integration.models.mixins import SourceMappingMixin


class CourseSource(SourceMappingMixin, Base):
    """Maps one canonical academic.courses row to one source identity."""

    __tablename__ = "course_sources"
    __table_args__ = (
        UniqueConstraint("source_system", "source_id", name="uq_course_sources_source"),
        CheckConstraint(
            "length(trim(source_system)) > 0", name="ck_course_sources_source_system_not_empty"
        ),
        CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_course_sources_source_id_not_empty"
        ),
        Index("ix_course_sources_course_id", "course_id"),
        {"schema": "integration"},
    )

    course_id: Mapped[int] = mapped_column(
        ForeignKey("academic.courses.id", ondelete="RESTRICT"), nullable=False
    )
