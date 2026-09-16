from sqlalchemy import Engine, select, text

from app.academic.models import Enrollment, Student
from app.integration.moodle.sync import run_moodle_sync
from tests.integration.moodle.fake_moodle import (
    enroll_student,
    ensure_cuenta_field,
    insert_course,
    insert_user,
    set_account_number,
)


def test_record_missing_from_a_later_extraction_is_not_physically_deleted(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    with moodle_engine.begin() as connection:
        cuenta_field_id = ensure_cuenta_field(connection)
        course_id = insert_course(connection, fullname="Intro to Programming")
        user_id = insert_user(connection, firstname="Ada", lastname="Lovelace")
        set_account_number(connection, user_id, cuenta_field_id, "1001")
        user_enrolment_id = enroll_student(connection, userid=user_id, courseid=course_id)

    first = run_moodle_sync(app_engine, moodle_engine, course_id)
    assert first.status == "SUCCESS"

    with app_engine.begin() as connection:
        assert len(connection.execute(select(Student)).all()) == 1
        assert len(connection.execute(select(Enrollment)).all()) == 1

    # The student's enrolment disappears from the next extraction — e.g. it
    # was suspended in Moodle. This must not be interpreted as a deletion.
    with moodle_engine.begin() as connection:
        connection.execute(
            text("UPDATE mdl_user_enrolments SET status = 1 WHERE id = :id"),
            {"id": user_enrolment_id},
        )

    second = run_moodle_sync(app_engine, moodle_engine, course_id)
    assert second.status == "SUCCESS"

    with app_engine.begin() as connection:
        # Still present — absence from one extraction is not a delete.
        students = connection.execute(select(Student)).all()
        enrollments = connection.execute(select(Enrollment)).all()

    assert len(students) == 1
    assert students[0].account_number == "1001"
    assert len(enrollments) == 1
