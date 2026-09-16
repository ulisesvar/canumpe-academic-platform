from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.integration.models.mixins import SourceMappingMixin


class AttendanceRecordSource(SourceMappingMixin, Base):
    """Maps one canonical academic.attendance_records row to one source identity."""

    __tablename__ = "attendance_record_sources"
    __table_args__ = (
        UniqueConstraint("source_system", "source_id", name="uq_attendance_record_sources_source"),
        CheckConstraint(
            "length(trim(source_system)) > 0",
            name="ck_attendance_record_sources_source_system_not_empty",
        ),
        CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_attendance_record_sources_source_id_not_empty"
        ),
        Index("ix_attendance_record_sources_attendance_record_id", "attendance_record_id"),
        {"schema": "integration"},
    )

    attendance_record_id: Mapped[int] = mapped_column(
        ForeignKey("academic.attendance_records.id", ondelete="RESTRICT"), nullable=False
    )
