from sqlalchemy.orm import Session

from app.academic.models import Course


def test_valid_course_can_be_inserted(db_session: Session) -> None:
    course = Course(name="Intro to Programming")
    db_session.add(course)
    db_session.commit()

    assert course.id is not None
    assert course.active is True


def test_source_id_is_not_the_canonical_primary_key(db_session: Session) -> None:
    """Canonical ids are internally generated, independent of any source id.

    The canonical table itself has no source-system column at all — that
    mapping lives in integration.course_sources instead.
    """
    assert "source_system" not in Course.__table__.columns
    assert "moodle_id" not in Course.__table__.columns

    course_a = Course(code="CS101", name="Intro to Programming")
    course_b = Course(code="CS102", name="Data Structures")
    db_session.add_all([course_a, course_b])
    db_session.commit()

    assert course_a.id is not None
    assert course_b.id is not None
    assert course_a.id != course_b.id
