from sqlalchemy import Engine, select

from app.academic.models import Student
from app.integration.attendance.sync import run_attendance_sync
from app.integration.models import StudentSource
from tests.integration.attendance.fake_attendance import insert_student
from tests.integration.attendance.helpers import seed_academic_student, seed_moodle_course_mapping

MOODLE_COURSE_ID = 2


def test_attendance_student_maps_to_existing_academic_student_by_account_number(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    academic_student_id = seed_academic_student(app_engine, account_number="1001")
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    with attendance_engine.begin() as connection:
        attendance_student_id = insert_student(connection, account_number="1001")

    outcome = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    assert outcome.status == "SUCCESS"
    with app_engine.begin() as connection:
        mapping = connection.execute(
            select(StudentSource).where(
                StudentSource.source_system == "attendance",
                StudentSource.source_id == str(attendance_student_id),
            )
        ).one()
    assert mapping.student_id == academic_student_id


def test_unknown_account_number_is_skipped_not_fatal(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    """An Attendance student whose account_number doesn't exist in Moodle
    yet must not fail the batch — see
    test_unresolved_student_skip.py for the full scenario (counters,
    no student/mapping created, later-sync replay).
    """
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    with attendance_engine.begin() as connection:
        insert_student(connection, account_number="does-not-exist")

    outcome = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    assert outcome.status == "SUCCESS"
    assert outcome.merge_result is not None
    assert outcome.merge_result.counters.rows_skipped == 1


def test_duplicate_account_number_fails(app_engine: Engine, attendance_engine: Engine) -> None:
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    with attendance_engine.begin() as connection:
        insert_student(connection, account_number="1001")
        insert_student(connection, account_number="1001")

    outcome = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    assert outcome.status == "FAILED"
    assert any("duplicate account_number" in issue for issue in outcome.issues)


def test_no_academic_student_is_created_from_attendance(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    seed_academic_student(app_engine, account_number="1001")
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    with attendance_engine.begin() as connection:
        insert_student(connection, account_number="1001")

    outcome = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    assert outcome.status == "SUCCESS"
    with app_engine.begin() as connection:
        students = connection.execute(select(Student)).all()
    assert len(students) == 1
