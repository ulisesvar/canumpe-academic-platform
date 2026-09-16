from sqlalchemy import Engine, select

from app.academic.models import AttendanceRecord, AttendanceSession
from app.integration.attendance.sync import run_attendance_sync
from app.integration.models import AttendanceRecordSource, AttendanceSessionSource, StudentSource
from tests.integration.attendance.fake_attendance import (
    insert_attendance,
    insert_session,
    insert_student,
    update_session_status,
)
from tests.integration.attendance.helpers import seed_academic_student, seed_moodle_course_mapping

MOODLE_COURSE_ID = 2


def _seed(app_engine: Engine, attendance_engine: Engine) -> tuple[int, int, int]:
    seed_academic_student(app_engine, account_number="1001")
    academic_course_id = seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    with attendance_engine.begin() as connection:
        student_id = insert_student(connection, account_number="1001")
        session_id = insert_session(connection, status="OPEN")
        insert_attendance(connection, session_id=session_id, student_id=student_id)
    return academic_course_id, student_id, session_id


def test_first_sync_inserts_attendance_session(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    academic_course_id, _, _ = _seed(app_engine, attendance_engine)

    outcome = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    assert outcome.status == "SUCCESS"
    with app_engine.begin() as connection:
        sessions = connection.execute(select(AttendanceSession)).all()
    assert len(sessions) == 1
    assert sessions[0].course_id == academic_course_id
    assert sessions[0].status == "OPEN"


def test_first_sync_inserts_attendance_record(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    _seed(app_engine, attendance_engine)

    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    with app_engine.begin() as connection:
        records = connection.execute(select(AttendanceRecord)).all()
    assert len(records) == 1


def test_source_mappings_are_created(app_engine: Engine, attendance_engine: Engine) -> None:
    _, student_id, session_id = _seed(app_engine, attendance_engine)

    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    with app_engine.begin() as connection:
        student_source = connection.execute(
            select(StudentSource).where(
                StudentSource.source_system == "attendance",
                StudentSource.source_id == str(student_id),
            )
        ).one()
        session_source = connection.execute(
            select(AttendanceSessionSource).where(
                AttendanceSessionSource.source_id == str(session_id)
            )
        ).one()
        record_source = connection.execute(select(AttendanceRecordSource)).one()

    assert student_source.source_system == "attendance"
    assert session_source.source_system == "attendance"
    assert record_source.source_system == "attendance"


def test_course_resolved_through_moodle_mapping(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    academic_course_id, _, _ = _seed(app_engine, attendance_engine)

    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    with app_engine.begin() as connection:
        session = connection.execute(select(AttendanceSession)).one()
    assert session.course_id == academic_course_id


def test_identical_second_sync_creates_no_duplicates(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    _seed(app_engine, attendance_engine)

    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)
    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    with app_engine.begin() as connection:
        assert len(connection.execute(select(AttendanceSession)).all()) == 1
        assert len(connection.execute(select(AttendanceRecord)).all()) == 1
        assert len(connection.execute(select(AttendanceSessionSource)).all()) == 1
        assert len(connection.execute(select(AttendanceRecordSource)).all()) == 1


def test_identical_second_sync_reports_unchanged(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    _seed(app_engine, attendance_engine)

    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)
    second = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    assert second.status == "SUCCESS"
    assert second.merge_result is not None
    assert second.merge_result.counters.rows_inserted == 0
    assert second.merge_result.counters.rows_updated == 0
    assert second.merge_result.counters.rows_unchanged == 3  # student + session + record


def test_session_status_change_updates_the_same_canonical_session(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    _, _, session_id = _seed(app_engine, attendance_engine)
    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    with app_engine.begin() as connection:
        original_id = connection.execute(select(AttendanceSession.id)).scalar_one()

    with attendance_engine.begin() as connection:
        update_session_status(connection, session_id, "CLOSED")

    outcome = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    with app_engine.begin() as connection:
        session = connection.execute(select(AttendanceSession)).one()

    assert outcome.merge_result is not None
    assert outcome.merge_result.counters.rows_updated == 1
    assert session.id == original_id
    assert session.status == "CLOSED"
