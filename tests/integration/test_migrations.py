from sqlalchemy import Engine, inspect

from alembic import command
from tests.conftest import alembic_config

ACADEMIC_TABLES = {"students", "courses", "enrollments"}
INTEGRATION_TABLES = {
    "student_sources",
    "course_sources",
    "enrollment_sources",
    "sync_runs",
    "sync_state",
}
EMPTY_SCHEMAS = ("raw_moodle", "raw_attendance", "staging", "auth")


def test_upgrade_head_succeeds_from_empty_database(db_engine: Engine) -> None:
    """The session-scoped `_migrated_schema` autouse fixture already had to
    run `alembic upgrade head` against a fresh database for any test in
    this suite to run at all — this just asserts the visible result.
    """
    table_names = inspect(db_engine).get_table_names(schema="academic")

    assert "students" in table_names


def test_expected_tables_and_constraints_are_present(db_engine: Engine) -> None:
    inspector = inspect(db_engine)

    assert set(inspector.get_table_names(schema="academic")) == ACADEMIC_TABLES
    assert set(inspector.get_table_names(schema="integration")) == INTEGRATION_TABLES
    for schema in EMPTY_SCHEMAS:
        assert inspector.get_table_names(schema=schema) == []

    student_unique_columns = {
        tuple(sorted(uc["column_names"]))
        for uc in inspector.get_unique_constraints("students", schema="academic")
    }
    assert ("account_number",) in student_unique_columns

    enrollment_unique_columns = {
        tuple(sorted(uc["column_names"]))
        for uc in inspector.get_unique_constraints("enrollments", schema="academic")
    }
    assert tuple(sorted(("student_id", "course_id"))) in enrollment_unique_columns

    enrollment_referred_tables = {
        fk["referred_table"] for fk in inspector.get_foreign_keys("enrollments", schema="academic")
    }
    assert enrollment_referred_tables == {"students", "courses"}

    sync_run_checks = {
        ck["name"] for ck in inspector.get_check_constraints("sync_runs", schema="integration")
    }
    assert "ck_sync_runs_status" in sync_run_checks


def test_downgrade_then_upgrade_is_clean(db_engine: Engine) -> None:
    cfg = alembic_config()

    try:
        command.downgrade(cfg, "0001_baseline")
        assert inspect(db_engine).get_table_names(schema="academic") == []
    finally:
        command.upgrade(cfg, "head")

    assert "students" in inspect(db_engine).get_table_names(schema="academic")


def test_upgrade_head_twice_is_safe() -> None:
    cfg = alembic_config()

    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
