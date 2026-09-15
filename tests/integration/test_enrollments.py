import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.academic.models import Course, Enrollment, Student

NONEXISTENT_ID = 999_999


def _student(db_session: Session, account_number: str) -> Student:
    student = Student(account_number=account_number, first_name="A", last_name="B")
    db_session.add(student)
    db_session.commit()
    return student


def _course(db_session: Session, code: str) -> Course:
    course = Course(code=code, name="Course")
    db_session.add(course)
    db_session.commit()
    return course


def test_valid_enrollment_can_be_inserted(db_session: Session) -> None:
    student = _student(db_session, "2001")
    course = _course(db_session, "C1")

    enrollment = Enrollment(student_id=student.id, course_id=course.id, status="active")
    db_session.add(enrollment)
    db_session.commit()

    assert enrollment.id is not None


def test_enrollment_with_nonexistent_student_fails(db_session: Session) -> None:
    course = _course(db_session, "C2")

    db_session.add(Enrollment(student_id=NONEXISTENT_ID, course_id=course.id))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_enrollment_with_nonexistent_course_fails(db_session: Session) -> None:
    student = _student(db_session, "2002")

    db_session.add(Enrollment(student_id=student.id, course_id=NONEXISTENT_ID))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_duplicate_student_course_enrollment_fails(db_session: Session) -> None:
    student = _student(db_session, "2003")
    course = _course(db_session, "C3")

    db_session.add(Enrollment(student_id=student.id, course_id=course.id))
    db_session.commit()

    db_session.add(Enrollment(student_id=student.id, course_id=course.id))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_active_defaults_to_true(db_session: Session) -> None:
    student = _student(db_session, "2004")
    course = _course(db_session, "C4")

    enrollment = Enrollment(student_id=student.id, course_id=course.id)
    db_session.add(enrollment)
    db_session.commit()
    db_session.refresh(enrollment)

    assert enrollment.active is True
