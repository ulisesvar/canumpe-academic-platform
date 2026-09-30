"""get_attendance_score against real rows — see
app.services.attendance_score_service. Uses the SAVEPOINT-rollback
db_session fixture.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.academic.models import AttendanceRecord, AttendanceSession, Course, Student
from app.services.attendance_score_service import get_attendance_score

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def _course(db_session: Session, name: str = "Course") -> int:
    course = Course(name=name)
    db_session.add(course)
    db_session.commit()
    return course.id


def _student(db_session: Session, account_number: str) -> int:
    student = Student(account_number=account_number, first_name="A", last_name="B")
    db_session.add(student)
    db_session.commit()
    return student.id


def _session(db_session: Session, course_id: int, status: str = "CLOSED", n: int = 0) -> int:
    opened_at = T0 + timedelta(days=n)
    session = AttendanceSession(
        course_id=course_id,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(hours=1) if status == "CLOSED" else None,
        status=status,
    )
    db_session.add(session)
    db_session.commit()
    return session.id


def _attend(db_session: Session, session_id: int, student_id: int) -> None:
    db_session.add(
        AttendanceRecord(attendance_session_id=session_id, student_id=student_id, recorded_at=T0)
    )
    db_session.commit()


def test_no_sessions_at_all_yields_null_score(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "8301")

    score = get_attendance_score(db_session, student_id, course_id)

    assert (score.closed_sessions, score.present_sessions, score.absent_sessions) == (0, 0, 0)
    assert score.score_100 is None


def test_open_sessions_are_ignored(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "8302")
    open_id = _session(db_session, course_id, status="OPEN")
    _attend(db_session, open_id, student_id)

    score = get_attendance_score(db_session, student_id, course_id)

    assert (score.closed_sessions, score.present_sessions, score.absent_sessions) == (0, 0, 0)
    assert score.score_100 is None


def test_open_sessions_do_not_dilute_a_closed_session_score(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "8303")
    _attend(db_session, _session(db_session, course_id, n=0), student_id)
    _session(db_session, course_id, status="OPEN", n=1)

    score = get_attendance_score(db_session, student_id, course_id)

    assert (score.closed_sessions, score.present_sessions) == (1, 1)
    assert score.score_100 == Decimal(100)


def test_one_closed_session_with_a_record_is_one_hundred(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "8304")
    _attend(db_session, _session(db_session, course_id), student_id)

    score = get_attendance_score(db_session, student_id, course_id)

    assert (score.closed_sessions, score.present_sessions, score.absent_sessions) == (1, 1, 0)
    assert score.score_100 == Decimal(100)


def test_one_closed_session_without_a_record_is_a_real_zero(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "8305")
    _session(db_session, course_id)

    score = get_attendance_score(db_session, student_id, course_id)

    assert (score.closed_sessions, score.present_sessions, score.absent_sessions) == (1, 0, 1)
    assert score.score_100 == Decimal(0)


def test_eighteen_present_of_twenty_closed_is_ninety(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "8306")
    session_ids = [_session(db_session, course_id, n=n) for n in range(20)]
    for session_id in session_ids[:18]:
        _attend(db_session, session_id, student_id)

    score = get_attendance_score(db_session, student_id, course_id)

    assert (score.closed_sessions, score.present_sessions, score.absent_sessions) == (20, 18, 2)
    assert score.score_100 == Decimal(90)


def test_a_missing_record_in_a_closed_session_counts_as_absence(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "8307")
    first = _session(db_session, course_id, n=0)
    _session(db_session, course_id, n=1)  # no record for the student
    _attend(db_session, first, student_id)

    score = get_attendance_score(db_session, student_id, course_id)

    assert (score.closed_sessions, score.present_sessions, score.absent_sessions) == (2, 1, 1)
    assert score.score_100 == Decimal(50)


def test_another_students_attendance_does_not_count(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "8308")
    other_id = _student(db_session, "8309")
    for n in range(3):
        session_id = _session(db_session, course_id, n=n)
        _attend(db_session, session_id, other_id)

    score = get_attendance_score(db_session, student_id, course_id)

    assert (score.closed_sessions, score.present_sessions, score.absent_sessions) == (3, 0, 3)
    assert score.score_100 == Decimal(0)


def test_another_courses_sessions_and_attendance_do_not_count(db_session: Session) -> None:
    course_id = _course(db_session, "Mine")
    other_course_id = _course(db_session, "Other")
    student_id = _student(db_session, "8310")
    mine = _session(db_session, course_id, n=0)
    _attend(db_session, mine, student_id)
    for n in range(5):
        _attend(db_session, _session(db_session, other_course_id, n=n), student_id)

    score = get_attendance_score(db_session, student_id, course_id)
    other = get_attendance_score(db_session, student_id, other_course_id)

    assert (score.closed_sessions, score.present_sessions) == (1, 1)
    assert score.score_100 == Decimal(100)
    assert (other.closed_sessions, other.present_sessions) == (5, 5)


def test_duplicate_attendance_records_cannot_exist_or_distort_the_count(
    db_session: Session,
) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "8311")
    session_id = _session(db_session, course_id)
    _session(db_session, course_id, n=1)
    _attend(db_session, session_id, student_id)

    db_session.add(
        AttendanceRecord(attendance_session_id=session_id, student_id=student_id, recorded_at=T0)
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    score = get_attendance_score(db_session, student_id, course_id)

    assert (score.closed_sessions, score.present_sessions, score.absent_sessions) == (2, 1, 1)
    assert score.score_100 == Decimal(50)


def test_present_can_never_exceed_closed(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "8312")
    closed = _session(db_session, course_id, n=0)
    open_ = _session(db_session, course_id, status="OPEN", n=1)
    _attend(db_session, closed, student_id)
    _attend(db_session, open_, student_id)

    score = get_attendance_score(db_session, student_id, course_id)

    assert score.present_sessions <= score.closed_sessions
    assert (score.closed_sessions, score.present_sessions) == (1, 1)
