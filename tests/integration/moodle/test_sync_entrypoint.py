"""Exercises app.integration.moodle.sync.main() the way systemd would
run it: plain environment variables, no Docker Compose, no Docker DNS
hostname, no container-only assumptions. `main()` builds its own engines
from DATABASE_URL/MOODLE_DB_URL/MOODLE_COURSE_ID exactly as it would on
the CANUMPE host.
"""

import pytest
from sqlalchemy import Engine

from app.core.config import get_settings
from app.integration.moodle.config import get_moodle_sync_settings
from app.integration.moodle.sync import main
from tests.conftest import TEST_DATABASE_URL
from tests.integration.moodle.fake_moodle import (
    enroll_student,
    ensure_cuenta_field,
    insert_course,
    insert_user,
    set_account_number,
)


def _seed(moodle_engine: Engine) -> int:
    with moodle_engine.begin() as connection:
        cuenta_field_id = ensure_cuenta_field(connection)
        course_id = insert_course(connection, fullname="Intro to Programming")
        user_id = insert_user(connection, firstname="Ada", lastname="Lovelace")
        set_account_number(connection, user_id, cuenta_field_id, "1001")
        enroll_student(connection, userid=user_id, courseid=course_id)
    return course_id


def _run_main_with_env(monkeypatch: pytest.MonkeyPatch, course_id: int) -> int:
    # A plain systemd EnvironmentFile= sets exactly these three (plus
    # LOG_LEVEL/ENVIRONMENT, irrelevant here) — nothing Compose-specific.
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("MOODLE_DB_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("MOODLE_COURSE_ID", str(course_id))
    get_settings.cache_clear()
    get_moodle_sync_settings.cache_clear()
    try:
        return main()
    finally:
        get_settings.cache_clear()
        get_moodle_sync_settings.cache_clear()


def test_entrypoint_succeeds_from_plain_environment_variables(
    app_engine: Engine, moodle_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _seed(moodle_engine)

    exit_code = _run_main_with_env(monkeypatch, course_id)

    assert exit_code == 0


def test_entrypoint_returns_nonzero_exit_code_on_failure(
    app_engine: Engine, moodle_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero exit is what lets systemd (Type=oneshot) mark the run
    failed, independent of the integration.sync_runs bookkeeping.
    """
    course_id = _seed(moodle_engine)
    with moodle_engine.begin() as connection:
        stray_user_id = insert_user(connection, firstname="No", lastname="Cuenta")
        enroll_student(connection, userid=stray_user_id, courseid=course_id)

    exit_code = _run_main_with_env(monkeypatch, course_id)

    assert exit_code == 1
