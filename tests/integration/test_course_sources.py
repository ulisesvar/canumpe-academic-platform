import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.academic.models import Course
from app.integration.models import CourseSource


def _course(db_session: Session, code: str) -> Course:
    course = Course(code=code, name="Course")
    db_session.add(course)
    db_session.commit()
    return course


def test_mapping_to_a_valid_course_succeeds(db_session: Session) -> None:
    course = _course(db_session, "S1")

    mapping = CourseSource(course_id=course.id, source_system="moodle", source_id="55")
    db_session.add(mapping)
    db_session.commit()

    assert mapping.id is not None


def test_duplicate_source_identity_fails(db_session: Session) -> None:
    course = _course(db_session, "S2")

    db_session.add(CourseSource(course_id=course.id, source_system="moodle", source_id="56"))
    db_session.commit()

    db_session.add(CourseSource(course_id=course.id, source_system="moodle", source_id="56"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
