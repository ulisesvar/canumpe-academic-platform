from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ParticipationObservation(TimestampMixin, Base):
    """One manual observation of a student's participation in a course,
    valued 0, 1, 2 or 3 (0 is a real zero).

    The participation result is always derived from a student's
    observations at read time (see app.services.participation_service)
    — the average and 0-100 score are never stored here.

    (student_id, course_id) is a composite foreign key to
    academic.enrollments, so an observation can only exist for a
    student enrolled in that course — enforced by the database, not
    just application code.
    """

    __tablename__ = "participation_observations"
    __table_args__ = (
        CheckConstraint("value IN (0, 1, 2, 3)", name="ck_participation_observations_value"),
        ForeignKeyConstraint(
            ["student_id", "course_id"],
            ["academic.enrollments.student_id", "academic.enrollments.course_id"],
            name="fk_participation_observations_enrollment",
            ondelete="RESTRICT",
        ),
        Index("ix_participation_observations_course_student", "course_id", "student_id"),
        {"schema": "academic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(nullable=False)
    student_id: Mapped[int] = mapped_column(nullable=False)
    value: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    recorded_by_api_key_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.api_keys.id", ondelete="RESTRICT"), nullable=True
    )
