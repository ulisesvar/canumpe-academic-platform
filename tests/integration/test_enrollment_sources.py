import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.academic.models import Course, Enrollment, Student
from app.integration.models import EnrollmentSource


def _enrollment(db_session: Session, account_number: str, code: str) -> Enrollment:
    student = Student(account_number=account_number, first_name="A", last_name="B")
    course = Course(code=code, name="Course")
    db_session.add_all([student, course])
    db_session.commit()

    enrollment = Enrollment(student_id=student.id, course_id=course.id)
    db_session.add(enrollment)
    db_session.commit()
    return enrollment


def test_mapping_to_a_valid_enrollment_succeeds(db_session: Session) -> None:
    enrollment = _enrollment(db_session, "4001", "E1")

    mapping = EnrollmentSource(enrollment_id=enrollment.id, source_system="moodle", source_id="900")
    db_session.add(mapping)
    db_session.commit()

    assert mapping.id is not None


def test_duplicate_source_identity_fails(db_session: Session) -> None:
    enrollment = _enrollment(db_session, "4002", "E2")

    db_session.add(
        EnrollmentSource(enrollment_id=enrollment.id, source_system="moodle", source_id="901")
    )
    db_session.commit()

    db_session.add(
        EnrollmentSource(enrollment_id=enrollment.id, source_system="moodle", source_id="901")
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
