"""Shared setup helpers for Moodle grades pipeline tests.

Grades never create canonical students or courses themselves — they only
ever look up the existing Moodle mappings created by the primary
students/courses/enrollments sync. These helpers stand in for "that sync
already ran", seeding exactly the integration.student_sources/
course_sources state grades resolution depends on, without needing to
run the full students/courses/enrollments pipeline in every test.
"""

from sqlalchemy import Engine, insert

from app.academic.models import Course, Student
from app.integration.models import CourseSource, StudentSource

MOODLE_SOURCE_SYSTEM = "moodle"


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


def seed_moodle_student_mapping(
    app_engine: Engine, moodle_user_id: int, account_number: str = "1001"
) -> int:
    """Creates a canonical student and maps it to the given Moodle user id."""
    with app_engine.begin() as connection:
        academic_student_id = connection.execute(
            insert(Student)
            .values(account_number=account_number, first_name="Test", last_name="Student")
            .returning(Student.id)
        ).scalar_one()
        connection.execute(
            insert(StudentSource).values(
                student_id=academic_student_id,
                source_system=MOODLE_SOURCE_SYSTEM,
                source_id=str(moodle_user_id),
            )
        )
    return academic_student_id
