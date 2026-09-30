"""Explicit queries backing the Phase 8.1 participation-observation
endpoints — academic.* only. Contains no calculation policy (average,
score): that lives in app.services.participation_service. Nothing here
commits; the service owns the transaction.
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.academic.models import Enrollment, ParticipationObservation


def enrollment_exists(db: Session, student_id: int, course_id: int) -> bool:
    return (
        db.execute(
            select(Enrollment.id).where(
                Enrollment.student_id == student_id, Enrollment.course_id == course_id
            )
        ).scalar_one_or_none()
        is not None
    )


def insert_observation(
    db: Session,
    *,
    course_id: int,
    student_id: int,
    value: int,
    observed_at: datetime,
    recorded_by_api_key_id: int,
) -> RowMapping:
    return (
        db.execute(
            insert(ParticipationObservation)
            .values(
                course_id=course_id,
                student_id=student_id,
                value=value,
                observed_at=observed_at,
                recorded_by_api_key_id=recorded_by_api_key_id,
            )
            .returning(ParticipationObservation.id, ParticipationObservation.observed_at)
        )
        .mappings()
        .one()
    )


def list_observations(db: Session, course_id: int, student_id: int) -> Sequence[RowMapping]:
    """Every observation for this student in this course, oldest first,
    with the id as a tiebreaker for deterministic responses.
    """
    stmt = (
        select(
            ParticipationObservation.id,
            ParticipationObservation.value,
            ParticipationObservation.observed_at,
        )
        .where(
            ParticipationObservation.course_id == course_id,
            ParticipationObservation.student_id == student_id,
        )
        .order_by(ParticipationObservation.observed_at, ParticipationObservation.id)
    )
    return db.execute(stmt).mappings().all()


def delete_observation(db: Session, observation_id: int, course_id: int, student_id: int) -> bool:
    """Hard-deletes exactly one observation, and only if it belongs to
    this course and student. Returns False when nothing matched — a
    nonexistent observation and one belonging to someone else are
    indistinguishable to the caller.
    """
    deleted_id = db.execute(
        delete(ParticipationObservation)
        .where(
            ParticipationObservation.id == observation_id,
            ParticipationObservation.course_id == course_id,
            ParticipationObservation.student_id == student_id,
        )
        .returning(ParticipationObservation.id)
    ).scalar_one_or_none()
    return deleted_id is not None
