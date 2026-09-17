import pytest
from sqlalchemy import Engine, select, text

from app.academic.models import GradeItem, StudentGrade
from app.integration.models import SyncRun, SyncState
from app.integration.moodle import grades_sync as grades_sync_module
from app.integration.moodle.grades_sync import run_moodle_grades_sync
from tests.integration.moodle.fake_moodle import (
    insert_course,
    insert_grade_grade,
    insert_grade_item,
)
from tests.integration.moodle.grades_helpers import (
    seed_moodle_course_mapping,
    seed_moodle_student_mapping,
)

MOODLE_USER_ID = 3


def _seed_valid(moodle_engine: Engine, app_engine: Engine) -> int:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        item_id = insert_grade_item(connection, courseid=course_id, itemname="Tarea 01")
        insert_grade_grade(connection, itemid=item_id, userid=MOODLE_USER_ID, finalgrade=30)
    seed_moodle_course_mapping(app_engine, course_id)
    seed_moodle_student_mapping(app_engine, MOODLE_USER_ID)
    return course_id


def test_validation_failure_leaves_academic_unchanged_and_marks_run_failed(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id = _seed_valid(moodle_engine, app_engine)
    first = run_moodle_grades_sync(app_engine, moodle_engine, course_id)
    assert first.status == "SUCCESS"

    # A second mdl_grade_grades row for the exact same (item, student) —
    # naturally reachable since the fake source, like real Moodle grants,
    # has no unique constraint this pipeline can rely on.
    with moodle_engine.begin() as connection:
        item_id = connection.execute(text("SELECT id FROM mdl_grade_items")).scalar_one()
        insert_grade_grade(connection, itemid=item_id, userid=MOODLE_USER_ID, finalgrade=80)

    second = run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    assert second.status == "FAILED"
    assert any("duplicate grade" in issue for issue in second.issues)

    with app_engine.begin() as connection:
        assert len(connection.execute(select(GradeItem)).all()) == 1
        assert len(connection.execute(select(StudentGrade)).all()) == 1
        grade = connection.execute(select(StudentGrade)).one()
        assert grade.grade == 30  # unchanged from the first, successful run

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
    course_id = _seed_valid(moodle_engine, app_engine)

    real_merge_batch = grades_sync_module.merge_grades_batch

    def failing_merge_batch(connection, now, moodle_course_id):
        real_merge_batch(connection, now, moodle_course_id)
        raise RuntimeError("simulated merge failure")

    monkeypatch.setattr(grades_sync_module, "merge_grades_batch", failing_merge_batch)

    outcome = run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    assert outcome.status == "FAILED"
    with app_engine.begin() as connection:
        assert connection.execute(select(GradeItem)).all() == []
        assert connection.execute(select(StudentGrade)).all() == []
        assert connection.execute(select(SyncState)).all() == []

        failed_run = connection.execute(
            select(SyncRun).where(SyncRun.batch_id == outcome.batch_id)
        ).one()
        assert failed_run.status == "FAILED"
        assert "simulated merge failure" in (failed_run.error_message or "")
