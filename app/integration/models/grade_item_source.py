from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.integration.models.mixins import SourceMappingMixin


class GradeItemSource(SourceMappingMixin, Base):
    """Maps one canonical academic.grade_items row to one source identity."""

    __tablename__ = "grade_item_sources"
    __table_args__ = (
        UniqueConstraint("source_system", "source_id", name="uq_grade_item_sources_source"),
        CheckConstraint(
            "length(trim(source_system)) > 0", name="ck_grade_item_sources_source_system_not_empty"
        ),
        CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_grade_item_sources_source_id_not_empty"
        ),
        Index("ix_grade_item_sources_grade_item_id", "grade_item_id"),
        {"schema": "integration"},
    )

    grade_item_id: Mapped[int] = mapped_column(
        ForeignKey("academic.grade_items.id", ondelete="RESTRICT"), nullable=False
    )
