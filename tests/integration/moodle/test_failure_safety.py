import pytest
from sqlalchemy import Engine, select

from app.academic.models import Course, Enrollment, Student
from app.integration.models import SyncRun, SyncState
from app.integration.moodle import sync as sync_module
from app.integration.moodle.sync import run_moodle_sync
from tests.integration.moodle.fake_moodle import (
    enroll_student,
    ensure_cuenta_field,
    insert_course,
    insert_user,
    set_account_number,
)


def _seed_valid(moodle_engine: Engine) -> int:
    with moodle_engine.begin() as connection:
        cuenta_field_id = ensure_cuenta_field(connection)
        course_id = insert_course(connection, fullname="Intro to Programming")
        user_id = insert_user(connection, firstname="Ada", lastname="Lovelace")
        set_account_number(connection, user_id, cuenta_field_id, "1001")
        enroll_student(connection, userid=user_id, courseid=course_id)
    return course_id


def test_validation_failure_leaves_academic_unchanged_and_marks_run_failed(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    """A user enrolled but without a 'cuenta' value is invisible to the
    students query yet still enrolled — a real, naturally-occurring way
    for an enrollment to reference an unknown student_source_id.
    """
    course_id = _seed_valid(moodle_engine)
    first = run_moodle_sync(app_engine, moodle_engine, course_id)
    assert first.status == "SUCCESS"

    with moodle_engine.begin() as connection:
        stray_user_id = insert_user(connection, firstname="No", lastname="Cuenta")
        enroll_student(connection, userid=stray_user_id, courseid=course_id)

    second = run_moodle_sync(app_engine, moodle_engine, course_id)

    assert second.status == "FAILED"
    assert any("unknown student_source_id" in issue for issue in second.issues)

    with app_engine.begin() as connection:
        # Still exactly what the first, successful run produced.
        assert len(connection.execute(select(Student)).all()) == 1
        assert len(connection.execute(select(Course)).all()) == 1
        assert len(connection.execute(select(Enrollment)).all()) == 1

        failed_run = connection.execute(
            select(SyncRun).where(SyncRun.batch_id == second.batch_id)
        ).one()
        assert failed_run.status == "FAILED"
        assert failed_run.error_message

        state = connection.execute(select(SyncState)).one()
        assert state.state["last_batch_id"] == str(first.batch_id)


def test_merge_failure_rolls_back_canonical_changes_and_marks_run_failed(
    app_engine: Engine, moodle_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _seed_valid(moodle_engine)

    real_merge_batch = sync_module.merge_batch

    def failing_merge_batch(connection, now):
        real_merge_batch(connection, now)
        raise RuntimeError("simulated merge failure")

    monkeypatch.setattr(sync_module, "merge_batch", failing_merge_batch)

    outcome = run_moodle_sync(app_engine, moodle_engine, course_id)

    assert outcome.status == "FAILED"
    with app_engine.begin() as connection:
        assert connection.execute(select(Student)).all() == []
        assert connection.execute(select(Course)).all() == []
        assert connection.execute(select(Enrollment)).all() == []
        assert connection.execute(select(SyncState)).all() == []

        failed_run = connection.execute(
            select(SyncRun).where(SyncRun.batch_id == outcome.batch_id)
        ).one()
        assert failed_run.status == "FAILED"
        assert "simulated merge failure" in (failed_run.error_message or "")


def test_watermark_does_not_advance_after_a_failure_following_a_prior_success(
    app_engine: Engine, moodle_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _seed_valid(moodle_engine)
    first = run_moodle_sync(app_engine, moodle_engine, course_id)
    assert first.status == "SUCCESS"

    real_merge_batch = sync_module.merge_batch

    def failing_merge_batch(connection, now):
        real_merge_batch(connection, now)
        raise RuntimeError("simulated merge failure")

    monkeypatch.setattr(sync_module, "merge_batch", failing_merge_batch)

    second = run_moodle_sync(app_engine, moodle_engine, course_id)
    assert second.status == "FAILED"

    with app_engine.begin() as connection:
        state = connection.execute(select(SyncState)).one()

    assert state.state["last_batch_id"] == str(first.batch_id)
