from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.integration.models.mixins import SourceMappingMixin


class EnrollmentSource(SourceMappingMixin, Base):
    """Maps one canonical academic.enrollments row to one source identity."""

    __tablename__ = "enrollment_sources"
    __table_args__ = (
        UniqueConstraint("source_system", "source_id", name="uq_enrollment_sources_source"),
        CheckConstraint(
            "length(trim(source_system)) > 0", name="ck_enrollment_sources_source_system_not_empty"
        ),
        CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_enrollment_sources_source_id_not_empty"
        ),
        Index("ix_enrollment_sources_enrollment_id", "enrollment_id"),
        {"schema": "integration"},
    )

    enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("academic.enrollments.id", ondelete="RESTRICT"), nullable=False
    )
