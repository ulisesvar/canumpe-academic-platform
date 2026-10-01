"""Participation observations (Phase 8.1).

A student's participation result is derived from their observations at
read time, never stored:

    participation_average   = arithmetic mean of all observation values
    participation_score_100 = (participation_average / 3) * 100

No observations means count 0 and an average and score of 0 — the academic
rule is that participation without observations is 0 (so it never leaves the
attendance/participation category unevaluated); a recorded 0 is, of course,
also a real zero. This function is the single source of that rule: the
participation endpoints, the evaluation and the gradebook all read it from
here. Every intermediate value is
a full-precision Decimal; rounding happens only when the response
objects are built (app.services.grade_normalization.round2), never fed
back into further arithmetic.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.api.schemas.participation import (
    ParticipationListResponse,
    ParticipationObservationItem,
    ParticipationObservationRequest,
    ParticipationRecordedResponse,
    ParticipationSummaryResponse,
)
from app.auth.models import ApiKey
from app.repositories import evaluation_repository as course_repo
from app.repositories import participation_repository as repo
from app.repositories import student_read_repository as student_repo
from app.services.errors import CourseNotFoundError
from app.services.grade_normalization import round2_or_none
from app.services.student_read_service import StudentNotFoundError

_MAX_OBSERVATION_VALUE = Decimal(3)
_HUNDRED = Decimal(100)


class StudentNotEnrolledError(Exception):
    """Raised when a participation observation is requested for a
    student who isn't enrolled in the given course.
    """

    def __init__(self, student_id: int, course_id: int) -> None:
        self.student_id = student_id
        self.course_id = course_id
        super().__init__(f"student_id={student_id!r} is not enrolled in course_id={course_id!r}")


class ParticipationObservationNotFoundError(Exception):
    """Raised when a participation observation doesn't exist for the
    given course and student — including when it exists for a different
    course or student.
    """

    def __init__(self, observation_id: int) -> None:
        self.observation_id = observation_id
        super().__init__(f"participation observation {observation_id!r} not found")


@dataclass(frozen=True)
class ParticipationSummary:
    count: int
    average: Decimal
    score_100: Decimal


def summarize_participation(values: Sequence[int]) -> ParticipationSummary:
    if not values:
        return ParticipationSummary(count=0, average=Decimal(0), score_100=Decimal(0))
    average = Decimal(sum(values)) / Decimal(len(values))
    return ParticipationSummary(
        count=len(values),
        average=average,
        score_100=average / _MAX_OBSERVATION_VALUE * _HUNDRED,
    )


def _ensure_course_and_student(db: Session, course_id: int, student_id: int) -> None:
    if not course_repo.course_exists(db, course_id):
        raise CourseNotFoundError(course_id)
    if not student_repo.student_exists(db, student_id):
        raise StudentNotFoundError(student_id)


def _ensure_enrolled(db: Session, course_id: int, student_id: int) -> None:
    _ensure_course_and_student(db, course_id, student_id)
    if not repo.enrollment_exists(db, student_id, course_id):
        raise StudentNotEnrolledError(student_id, course_id)


def _current_summary(db: Session, course_id: int, student_id: int) -> ParticipationSummary:
    rows = repo.list_observations(db, course_id, student_id)
    return summarize_participation([row["value"] for row in rows])


def record_observation(
    db: Session,
    course_id: int,
    student_id: int,
    payload: ParticipationObservationRequest,
    api_key: ApiKey,
) -> ParticipationRecordedResponse:
    _ensure_enrolled(db, course_id, student_id)

    row = repo.insert_observation(
        db,
        course_id=course_id,
        student_id=student_id,
        value=payload.value,
        observed_at=payload.observed_at or datetime.now(UTC),
        recorded_by_api_key_id=api_key.id,
    )
    summary = _current_summary(db, course_id, student_id)
    db.commit()

    return ParticipationRecordedResponse(
        observation_id=row["id"],
        value=payload.value,
        observed_at=row["observed_at"],
        participation_count=summary.count,
        participation_average=round2_or_none(summary.average),
        participation_score_100=round2_or_none(summary.score_100),
    )


def get_participation(db: Session, course_id: int, student_id: int) -> ParticipationListResponse:
    _ensure_enrolled(db, course_id, student_id)

    rows = repo.list_observations(db, course_id, student_id)
    summary = summarize_participation([row["value"] for row in rows])

    return ParticipationListResponse(
        student_id=student_id,
        course_id=course_id,
        observations=[
            ParticipationObservationItem(
                observation_id=row["id"], value=row["value"], observed_at=row["observed_at"]
            )
            for row in rows
        ],
        participation_count=summary.count,
        participation_average=round2_or_none(summary.average),
        participation_score_100=round2_or_none(summary.score_100),
    )


def delete_observation(
    db: Session, course_id: int, student_id: int, observation_id: int
) -> ParticipationSummaryResponse:
    _ensure_course_and_student(db, course_id, student_id)

    if not repo.delete_observation(db, observation_id, course_id, student_id):
        raise ParticipationObservationNotFoundError(observation_id)

    summary = _current_summary(db, course_id, student_id)
    db.commit()

    return ParticipationSummaryResponse(
        student_id=student_id,
        course_id=course_id,
        participation_count=summary.count,
        participation_average=round2_or_none(summary.average),
        participation_score_100=round2_or_none(summary.score_100),
    )
