from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.integration.models.mixins import SourceMappingMixin


class AttendanceSessionSource(SourceMappingMixin, Base):
    """Maps one canonical academic.attendance_sessions row to one source identity."""

    __tablename__ = "attendance_session_sources"
    __table_args__ = (
        UniqueConstraint(
            "source_system", "source_id", name="uq_attendance_session_sources_source"
        ),
        CheckConstraint(
            "length(trim(source_system)) > 0",
            name="ck_attendance_session_sources_source_system_not_empty",
        ),
        CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_attendance_session_sources_source_id_not_empty"
        ),
        Index("ix_attendance_session_sources_attendance_session_id", "attendance_session_id"),
        {"schema": "integration"},
    )

    attendance_session_id: Mapped[int] = mapped_column(
        ForeignKey("academic.attendance_sessions.id", ondelete="RESTRICT"), nullable=False
    )
