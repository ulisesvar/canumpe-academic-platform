import time

from sqlalchemy import Engine, select

from app.academic.models import Student
from app.integration.models import StudentSource
from app.integration.moodle.sync import run_moodle_sync
from tests.integration.moodle.fake_moodle import (
    enroll_student,
    ensure_cuenta_field,
    insert_course,
    insert_user,
    set_account_number,
    update_user_lastname,
)


def _seed(moodle_engine: Engine) -> tuple[int, int]:
    with moodle_engine.begin() as connection:
        cuenta_field_id = ensure_cuenta_field(connection)
        course_id = insert_course(connection, fullname="Intro to Programming")
        user_id = insert_user(connection, firstname="Ada", lastname="Lovelace")
        set_account_number(connection, user_id, cuenta_field_id, "1001")
        enroll_student(connection, userid=user_id, courseid=course_id)
    return course_id, user_id


def test_changed_canonical_row_explicitly_advances_updated_at(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, user_id = _seed(moodle_engine)
    run_moodle_sync(app_engine, moodle_engine, course_id)
    with app_engine.begin() as connection:
        original_updated_at = connection.execute(select(Student.updated_at)).scalar_one()

    time.sleep(0.01)
    with moodle_engine.begin() as connection:
        update_user_lastname(connection, user_id, "Lovelace-Byron")
    run_moodle_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        new_updated_at = connection.execute(select(Student.updated_at)).scalar_one()

    assert new_updated_at > original_updated_at


def test_unchanged_source_mapping_still_advances_last_seen_at_and_synced_at(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, _ = _seed(moodle_engine)
    run_moodle_sync(app_engine, moodle_engine, course_id)
    with app_engine.begin() as connection:
        first = connection.execute(
            select(StudentSource.last_seen_at, StudentSource.synced_at)
        ).one()

    time.sleep(0.01)
    outcome = run_moodle_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        second = connection.execute(
            select(StudentSource.last_seen_at, StudentSource.synced_at)
        ).one()

    assert outcome.merge_result is not None
    assert outcome.merge_result.counters.rows_unchanged == 3
    assert second.last_seen_at > first.last_seen_at
    assert second.synced_at > first.synced_at


def test_unchanged_canonical_row_does_not_advance_updated_at(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    """The flip side of the two tests above: when nothing about the
    source content changed, the canonical row's updated_at must stay
    put even though the source mapping's last_seen_at/synced_at do not.
    """
    course_id, _ = _seed(moodle_engine)
    run_moodle_sync(app_engine, moodle_engine, course_id)
    with app_engine.begin() as connection:
        original_updated_at = connection.execute(select(Student.updated_at)).scalar_one()

    time.sleep(0.01)
    run_moodle_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        new_updated_at = connection.execute(select(Student.updated_at)).scalar_one()

    assert new_updated_at == original_updated_at
