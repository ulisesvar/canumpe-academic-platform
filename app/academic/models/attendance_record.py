from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AttendanceRecord(TimestampMixin, Base):
    """One student's recorded attendance at one canonical attendance session.

    Only the fact "this student recorded attendance at this session" is
    stored — no location/distance data (see the README's minimal-data
    principle) and no derived presence/absence semantics.
    """

    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint(
            "attendance_session_id", "student_id", name="uq_attendance_records_session_student"
        ),
        Index("ix_attendance_records_attendance_session_id", "attendance_session_id"),
        Index("ix_attendance_records_student_id", "student_id"),
        {"schema": "academic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    attendance_session_id: Mapped[int] = mapped_column(
        ForeignKey("academic.attendance_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("academic.students.id", ondelete="RESTRICT"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
