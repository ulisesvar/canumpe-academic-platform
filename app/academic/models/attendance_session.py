from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AttendanceSession(TimestampMixin, Base):
    """One canonical attendance-taking session for a course.

    Course association comes from the Moodle course mapping (see
    app.integration.attendance) — the Attendance source has no course id
    of its own. Only source facts are recorded here; absence/attendance
    percentages are future API/business logic, not ingestion.
    """

    __tablename__ = "attendance_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED')", name="ck_attendance_sessions_status"
        ),
        Index("ix_attendance_sessions_course_id", "course_id"),
        {"schema": "academic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("academic.courses.id", ondelete="RESTRICT"), nullable=False
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
