"""academic.participation_observations — database-level guarantees
(value CHECK, enrollment composite foreign key). Uses the SAVEPOINT-
rollback db_session fixture.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.academic.models import Course, Enrollment, ParticipationObservation, Student


def _student(db_session: Session, account_number: str) -> int:
    student = Student(account_number=account_number, first_name="A", last_name="B")
    db_session.add(student)
    db_session.commit()
    return student.id


def _course(db_session: Session) -> int:
    course = Course(name="Course")
    db_session.add(course)
    db_session.commit()
    return course.id


def _enroll(db_session: Session, student_id: int, course_id: int) -> None:
    db_session.add(Enrollment(student_id=student_id, course_id=course_id))
    db_session.commit()


@pytest.mark.parametrize("value", [0, 1, 2, 3])
def test_valid_values_can_be_inserted(db_session: Session, value: int) -> None:
    student_id = _student(db_session, "8101")
    course_id = _course(db_session)
    _enroll(db_session, student_id, course_id)

    db_session.add(
        ParticipationObservation(course_id=course_id, student_id=student_id, value=value)
    )
    db_session.commit()

    stored = (
        db_session.query(ParticipationObservation.value)
        .filter_by(course_id=course_id, student_id=student_id)
        .one()
    )
    assert stored.value == value


@pytest.mark.parametrize("value", [-1, 4])
def test_out_of_range_values_are_rejected_by_the_database(db_session: Session, value: int) -> None:
    student_id = _student(db_session, "8102")
    course_id = _course(db_session)
    _enroll(db_session, student_id, course_id)

    db_session.add(
        ParticipationObservation(course_id=course_id, student_id=student_id, value=value)
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_observation_for_an_unenrolled_student_is_rejected_by_the_database(
    db_session: Session,
) -> None:
    student_id = _student(db_session, "8103")
    course_id = _course(db_session)

    db_session.add(ParticipationObservation(course_id=course_id, student_id=student_id, value=3))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_enrollment_with_observations_cannot_be_deleted(db_session: Session) -> None:
    student_id = _student(db_session, "8104")
    course_id = _course(db_session)
    _enroll(db_session, student_id, course_id)
    db_session.add(ParticipationObservation(course_id=course_id, student_id=student_id, value=2))
    db_session.commit()

    enrollment = (
        db_session.query(Enrollment).filter_by(student_id=student_id, course_id=course_id).one()
    )
    db_session.delete(enrollment)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_multiple_observations_per_student_and_course_are_allowed(db_session: Session) -> None:
    student_id = _student(db_session, "8105")
    course_id = _course(db_session)
    _enroll(db_session, student_id, course_id)

    for value in (3, 3, 3):
        db_session.add(
            ParticipationObservation(course_id=course_id, student_id=student_id, value=value)
        )
    db_session.commit()

    assert (
        db_session.query(ParticipationObservation)
        .filter_by(course_id=course_id, student_id=student_id)
        .count()
        == 3
    )
