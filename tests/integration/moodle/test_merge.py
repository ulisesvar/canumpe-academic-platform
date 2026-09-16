from sqlalchemy import Engine, select

from app.academic.models import Course, Enrollment, Student
from app.integration.models import CourseSource, EnrollmentSource, StudentSource
from app.integration.moodle.sync import run_moodle_sync
from tests.integration.moodle.fake_moodle import (
    enroll_student,
    ensure_cuenta_field,
    insert_course,
    insert_user,
    set_account_number,
    update_course_fullname,
    update_user_lastname,
)


def _seed(moodle_engine: Engine) -> tuple[int, int]:
    with moodle_engine.begin() as connection:
        cuenta_field_id = ensure_cuenta_field(connection)
        course_id = insert_course(connection, fullname="Intro to Programming", shortname="CS101")
        user_id = insert_user(connection, firstname="Ada", lastname="Lovelace")
        set_account_number(connection, user_id, cuenta_field_id, "1001")
        enroll_student(connection, userid=user_id, courseid=course_id)
    return course_id, user_id


def test_first_sync_inserts_student(app_engine: Engine, moodle_engine: Engine) -> None:
    course_id, _ = _seed(moodle_engine)

    outcome = run_moodle_sync(app_engine, moodle_engine, course_id)

    assert outcome.status == "SUCCESS"
    with app_engine.begin() as connection:
        students = connection.execute(select(Student)).all()
    assert len(students) == 1
    assert students[0].account_number == "1001"


def test_first_sync_inserts_course(app_engine: Engine, moodle_engine: Engine) -> None:
    course_id, _ = _seed(moodle_engine)

    run_moodle_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        courses = connection.execute(select(Course)).all()
    assert len(courses) == 1
    assert courses[0].name == "Intro to Programming"


def test_first_sync_inserts_enrollment(app_engine: Engine, moodle_engine: Engine) -> None:
    course_id, _ = _seed(moodle_engine)

    run_moodle_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        enrollments = connection.execute(select(Enrollment)).all()
    assert len(enrollments) == 1


def test_source_mappings_are_created(app_engine: Engine, moodle_engine: Engine) -> None:
    course_id, user_id = _seed(moodle_engine)

    run_moodle_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        student_source = connection.execute(select(StudentSource)).one()
        course_source = connection.execute(select(CourseSource)).one()
        enrollment_source = connection.execute(select(EnrollmentSource)).one()

    assert student_source.source_system == "moodle"
    assert student_source.source_id == str(user_id)
    assert course_source.source_id == str(course_id)
    assert enrollment_source.source_system == "moodle"


def test_identical_second_sync_creates_no_duplicates(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, _ = _seed(moodle_engine)

    run_moodle_sync(app_engine, moodle_engine, course_id)
    run_moodle_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        assert len(connection.execute(select(Student)).all()) == 1
        assert len(connection.execute(select(Course)).all()) == 1
        assert len(connection.execute(select(Enrollment)).all()) == 1
        assert len(connection.execute(select(StudentSource)).all()) == 1
        assert len(connection.execute(select(CourseSource)).all()) == 1
        assert len(connection.execute(select(EnrollmentSource)).all()) == 1


def test_identical_second_sync_reports_unchanged(app_engine: Engine, moodle_engine: Engine) -> None:
    course_id, _ = _seed(moodle_engine)

    run_moodle_sync(app_engine, moodle_engine, course_id)
    second = run_moodle_sync(app_engine, moodle_engine, course_id)

    assert second.status == "SUCCESS"
    assert second.merge_result is not None
    assert second.merge_result.counters.rows_inserted == 0
    assert second.merge_result.counters.rows_updated == 0
    assert second.merge_result.counters.rows_unchanged == 3  # student + course + enrollment


def test_changed_student_updates_the_same_canonical_student(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, user_id = _seed(moodle_engine)
    run_moodle_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        original_id = connection.execute(select(Student.id)).scalar_one()

    with moodle_engine.begin() as connection:
        update_user_lastname(connection, user_id, "Lovelace-Byron")

    outcome = run_moodle_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        student = connection.execute(select(Student)).one()

    assert outcome.merge_result is not None
    assert outcome.merge_result.counters.rows_updated == 1
    assert student.id == original_id
    assert student.last_name == "Lovelace-Byron"


def test_changed_course_updates_the_same_canonical_course(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, _ = _seed(moodle_engine)
    run_moodle_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        original_id = connection.execute(select(Course.id)).scalar_one()

    with moodle_engine.begin() as connection:
        update_course_fullname(connection, course_id, "Intro to Programming (revised)")

    outcome = run_moodle_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        course = connection.execute(select(Course)).one()

    assert outcome.merge_result is not None
    assert outcome.merge_result.counters.rows_updated == 1
    assert course.id == original_id
    assert course.name == "Intro to Programming (revised)"


def test_no_duplicate_mappings_after_repeated_syncs(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, user_id = _seed(moodle_engine)

    run_moodle_sync(app_engine, moodle_engine, course_id)
    run_moodle_sync(app_engine, moodle_engine, course_id)
    run_moodle_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        mappings = connection.execute(
            select(StudentSource).where(StudentSource.source_id == str(user_id))
        ).all()

    assert len(mappings) == 1
