import pytest
from sqlalchemy import Engine, select

from app.academic.models import AttendanceRecord, AttendanceSession
from app.integration.attendance import sync as sync_module
from app.integration.attendance.sync import run_attendance_sync
from app.integration.models import SyncRun, SyncState
from tests.integration.attendance.fake_attendance import (
    insert_attendance,
    insert_session,
    insert_student,
)
from tests.integration.attendance.helpers import seed_academic_student, seed_moodle_course_mapping

MOODLE_COURSE_ID = 2


def _seed_valid(app_engine: Engine, attendance_engine: Engine) -> None:
    seed_academic_student(app_engine, account_number="1001")
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    with attendance_engine.begin() as connection:
        student_id = insert_student(connection, account_number="1001")
        session_id = insert_session(connection, status="OPEN")
        insert_attendance(connection, session_id=session_id, student_id=student_id)


def test_validation_failure_leaves_academic_unchanged_and_marks_run_failed(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    _seed_valid(app_engine, attendance_engine)
    first = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)
    assert first.status == "SUCCESS"

    # A stray attendance referencing a student that was never itself
    # recorded as an Attendance student — a broken reference reaching
    # the real pipeline naturally (no FK on the fake source, same as the
    # real Attendance schema only constrains session_id/student_id
    # within its own database).
    with attendance_engine.begin() as connection:
        session_id = insert_session(connection, status="OPEN")
        insert_attendance(connection, session_id=session_id, student_id=999_999)

    second = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    assert second.status == "FAILED"
    assert any("unknown student_source_id" in issue for issue in second.issues)

    with app_engine.begin() as connection:
        assert len(connection.execute(select(AttendanceSession)).all()) == 1
        assert len(connection.execute(select(AttendanceRecord)).all()) == 1

        failed_run = connection.execute(
            select(SyncRun).where(SyncRun.batch_id == second.batch_id)
        ).one()
        assert failed_run.status == "FAILED"
        assert failed_run.error_message

        state = connection.execute(select(SyncState)).one()
        assert state.state["last_batch_id"] == str(first.batch_id)


def test_merge_failure_rolls_back_canonical_changes_and_marks_run_failed(
    app_engine: Engine, attendance_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_valid(app_engine, attendance_engine)

    real_merge_batch = sync_module.merge_batch

    def failing_merge_batch(connection, now, moodle_course_id):
        real_merge_batch(connection, now, moodle_course_id)
        raise RuntimeError("simulated merge failure")

    monkeypatch.setattr(sync_module, "merge_batch", failing_merge_batch)

    outcome = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    assert outcome.status == "FAILED"
    with app_engine.begin() as connection:
        assert connection.execute(select(AttendanceSession)).all() == []
        assert connection.execute(select(AttendanceRecord)).all() == []
        assert connection.execute(select(SyncState)).all() == []

        failed_run = connection.execute(
            select(SyncRun).where(SyncRun.batch_id == outcome.batch_id)
        ).one()
        assert failed_run.status == "FAILED"
        assert "simulated merge failure" in (failed_run.error_message or "")
