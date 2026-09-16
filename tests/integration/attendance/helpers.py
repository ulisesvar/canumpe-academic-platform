"""Shared setup helpers for Attendance pipeline tests.

Attendance never creates canonical students or courses itself — these
helpers stand in for "the Moodle sync already ran", seeding exactly the
academic.students / integration.course_sources state Attendance
reconciliation depends on.
"""

from sqlalchemy import Engine, insert

from app.academic.models import Course, Student
from app.integration.models import CourseSource

MOODLE_SOURCE_SYSTEM = "moodle"


def seed_academic_student(app_engine: Engine, account_number: str) -> int:
    with app_engine.begin() as connection:
        return connection.execute(
            insert(Student)
            .values(account_number=account_number, first_name="Test", last_name="Student")
            .returning(Student.id)
        ).scalar_one()


def seed_moodle_course_mapping(app_engine: Engine, moodle_course_id: int) -> int:
    """Creates a canonical course and maps it to the given Moodle course id."""
    with app_engine.begin() as connection:
        academic_course_id = connection.execute(
            insert(Course).values(name="Test Course").returning(Course.id)
        ).scalar_one()
        connection.execute(
            insert(CourseSource).values(
                course_id=academic_course_id,
                source_system=MOODLE_SOURCE_SYSTEM,
                source_id=str(moodle_course_id),
            )
        )
    return academic_course_id
