from sqlalchemy import Engine, inspect

from alembic import command
from tests.conftest import alembic_config

PHASE1_ACADEMIC_TABLES = {"students", "courses", "enrollments"}
PHASE3_ACADEMIC_TABLES = PHASE1_ACADEMIC_TABLES | {"attendance_sessions", "attendance_records"}
ACADEMIC_TABLES = PHASE3_ACADEMIC_TABLES | {"grade_items", "student_grades"}

PHASE1_INTEGRATION_TABLES = {
    "student_sources",
    "course_sources",
    "enrollment_sources",
    "sync_runs",
    "sync_state",
}
PHASE3_INTEGRATION_TABLES = PHASE1_INTEGRATION_TABLES | {
    "attendance_session_sources",
    "attendance_record_sources",
}
PHASE3_INTEGRATION_TABLES_WITH_ISSUES = PHASE3_INTEGRATION_TABLES | {"sync_issues"}
INTEGRATION_TABLES = PHASE3_INTEGRATION_TABLES_WITH_ISSUES | {
    "grade_item_sources",
    "student_grade_sources",
}

PHASE1_RAW_MOODLE_TABLES = {"students", "courses", "enrollments"}
RAW_MOODLE_TABLES = PHASE1_RAW_MOODLE_TABLES | {"grade_items", "student_grades"}
RAW_ATTENDANCE_TABLES = {"students", "sessions", "attendances"}

PHASE3_STAGING_TABLES = {
    "students",
    "courses",
    "enrollments",
    "attendance_students",
    "attendance_sessions",
    "attendance_records",
}
STAGING_TABLES = PHASE3_STAGING_TABLES | {"grade_items", "student_grades"}
EMPTY_SCHEMAS = ("auth",)


def test_upgrade_head_succeeds_from_empty_database(db_engine: Engine) -> None:
    """The session-scoped `_migrated_schema` autouse fixture already had to
    run `alembic upgrade head` against a fresh database for any test in
    this suite to run at all — this just asserts the visible result.
    """
    table_names = inspect(db_engine).get_table_names(schema="academic")

    assert "students" in table_names
    assert "attendance_sessions" in table_names
    assert "grade_items" in table_names


def test_expected_tables_and_constraints_are_present(db_engine: Engine) -> None:
    inspector = inspect(db_engine)

    assert set(inspector.get_table_names(schema="academic")) == ACADEMIC_TABLES
    assert set(inspector.get_table_names(schema="integration")) == INTEGRATION_TABLES
    assert set(inspector.get_table_names(schema="raw_moodle")) == RAW_MOODLE_TABLES
    assert set(inspector.get_table_names(schema="raw_attendance")) == RAW_ATTENDANCE_TABLES
    assert set(inspector.get_table_names(schema="staging")) == STAGING_TABLES
    for schema in EMPTY_SCHEMAS:
        assert inspector.get_table_names(schema=schema) == []

    raw_moodle_students_unique = {
        tuple(sorted(uc["column_names"]))
        for uc in inspector.get_unique_constraints("students", schema="raw_moodle")
    }
    assert tuple(sorted(("batch_id", "source_id"))) in raw_moodle_students_unique

    raw_attendance_students_unique = {
        tuple(sorted(uc["column_names"]))
        for uc in inspector.get_unique_constraints("students", schema="raw_attendance")
    }
    assert tuple(sorted(("batch_id", "source_id"))) in raw_attendance_students_unique

    staging_students_unique = {
        tuple(sorted(uc["column_names"]))
        for uc in inspector.get_unique_constraints("students", schema="staging")
    }
    assert tuple(sorted(("source_system", "source_id"))) in staging_students_unique

    staging_attendance_students_unique = {
        tuple(sorted(uc["column_names"]))
        for uc in inspector.get_unique_constraints("attendance_students", schema="staging")
    }
    assert tuple(sorted(("source_system", "source_id"))) in staging_attendance_students_unique

    staging_student_grades_unique = {
        tuple(sorted(uc["column_names"]))
        for uc in inspector.get_unique_constraints("student_grades", schema="staging")
    }
    assert tuple(sorted(("source_system", "source_id"))) in staging_student_grades_unique

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

    attendance_records_unique_columns = {
        tuple(sorted(uc["column_names"]))
        for uc in inspector.get_unique_constraints("attendance_records", schema="academic")
    }
    assert (
        tuple(sorted(("attendance_session_id", "student_id"))) in attendance_records_unique_columns
    )

    student_grades_unique_columns = {
        tuple(sorted(uc["column_names"]))
        for uc in inspector.get_unique_constraints("student_grades", schema="academic")
    }
    assert tuple(sorted(("grade_item_id", "student_id"))) in student_grades_unique_columns

    enrollment_referred_tables = {
        fk["referred_table"] for fk in inspector.get_foreign_keys("enrollments", schema="academic")
    }
    assert enrollment_referred_tables == {"students", "courses"}

    attendance_records_referred_tables = {
        fk["referred_table"]
        for fk in inspector.get_foreign_keys("attendance_records", schema="academic")
    }
    assert attendance_records_referred_tables == {"attendance_sessions", "students"}

    student_grades_referred_tables = {
        fk["referred_table"]
        for fk in inspector.get_foreign_keys("student_grades", schema="academic")
    }
    assert student_grades_referred_tables == {"grade_items", "students"}

    grade_items_referred_tables = {
        fk["referred_table"] for fk in inspector.get_foreign_keys("grade_items", schema="academic")
    }
    assert grade_items_referred_tables == {"courses"}

    grade_item_sources_unique_columns = {
        tuple(sorted(uc["column_names"]))
        for uc in inspector.get_unique_constraints("grade_item_sources", schema="integration")
    }
    assert tuple(sorted(("source_system", "source_id"))) in grade_item_sources_unique_columns

    student_grade_sources_unique_columns = {
        tuple(sorted(uc["column_names"]))
        for uc in inspector.get_unique_constraints("student_grade_sources", schema="integration")
    }
    assert tuple(sorted(("source_system", "source_id"))) in student_grade_sources_unique_columns

    sync_run_checks = {
        ck["name"] for ck in inspector.get_check_constraints("sync_runs", schema="integration")
    }
    assert "ck_sync_runs_status" in sync_run_checks

    sync_issues_unique_columns = {
        tuple(sorted(uc["column_names"]))
        for uc in inspector.get_unique_constraints("sync_issues", schema="integration")
    }
    assert (
        tuple(sorted(("source_system", "issue_type", "source_entity", "source_id")))
        in sync_issues_unique_columns
    )

    sync_issues_checks = {
        ck["name"] for ck in inspector.get_check_constraints("sync_issues", schema="integration")
    }
    assert "ck_sync_issues_status" in sync_issues_checks


def test_downgrade_then_upgrade_is_clean(db_engine: Engine) -> None:
    cfg = alembic_config()

    try:
        command.downgrade(cfg, "0001_baseline")
        assert inspect(db_engine).get_table_names(schema="academic") == []
        assert inspect(db_engine).get_table_names(schema="raw_moodle") == []
        assert inspect(db_engine).get_table_names(schema="raw_attendance") == []
        assert inspect(db_engine).get_table_names(schema="staging") == []
    finally:
        command.upgrade(cfg, "head")

    assert "students" in inspect(db_engine).get_table_names(schema="academic")
    assert "attendance_sessions" in inspect(db_engine).get_table_names(schema="academic")
    assert "grade_items" in inspect(db_engine).get_table_names(schema="academic")
    assert "students" in inspect(db_engine).get_table_names(schema="raw_moodle")
    assert "grade_items" in inspect(db_engine).get_table_names(schema="raw_moodle")
    assert "students" in inspect(db_engine).get_table_names(schema="raw_attendance")
    assert "students" in inspect(db_engine).get_table_names(schema="staging")
    assert "grade_items" in inspect(db_engine).get_table_names(schema="staging")


def test_downgrade_one_step_from_head_removes_only_grades_ingestion(db_engine: Engine) -> None:
    cfg = alembic_config()

    try:
        command.downgrade(cfg, "0005_sync_issues")
        assert set(inspect(db_engine).get_table_names(schema="academic")) == PHASE3_ACADEMIC_TABLES
        integration_tables = set(inspect(db_engine).get_table_names(schema="integration"))
        assert integration_tables == PHASE3_INTEGRATION_TABLES_WITH_ISSUES
        assert "grade_item_sources" not in integration_tables
        assert "student_grade_sources" not in integration_tables
        assert (
            set(inspect(db_engine).get_table_names(schema="raw_moodle"))
            == PHASE1_RAW_MOODLE_TABLES
        )
        assert set(inspect(db_engine).get_table_names(schema="staging")) == PHASE3_STAGING_TABLES
    finally:
        command.upgrade(cfg, "head")

    assert "grade_items" in inspect(db_engine).get_table_names(schema="academic")
    assert "grade_item_sources" in inspect(db_engine).get_table_names(schema="integration")


def test_downgrade_one_step_from_head_removes_only_sync_issues(db_engine: Engine) -> None:
    cfg = alembic_config()

    try:
        command.downgrade(cfg, "0004_attendance_ingestion")
        integration_tables = set(inspect(db_engine).get_table_names(schema="integration"))
        assert integration_tables == PHASE3_INTEGRATION_TABLES
        assert "sync_issues" not in integration_tables
        # Attendance ingestion (0004) and everything before it is untouched.
        assert set(inspect(db_engine).get_table_names(schema="academic")) == PHASE3_ACADEMIC_TABLES
        assert (
            set(inspect(db_engine).get_table_names(schema="raw_attendance"))
            == RAW_ATTENDANCE_TABLES
        )
        assert set(inspect(db_engine).get_table_names(schema="staging")) == PHASE3_STAGING_TABLES
    finally:
        command.upgrade(cfg, "head")

    assert "sync_issues" in inspect(db_engine).get_table_names(schema="integration")


def test_downgrade_one_step_from_head_removes_only_attendance_ingestion(db_engine: Engine) -> None:
    cfg = alembic_config()

    try:
        command.downgrade(cfg, "0003_moodle_ingestion")
        assert inspect(db_engine).get_table_names(schema="raw_attendance") == []
        assert set(inspect(db_engine).get_table_names(schema="staging")) == {
            "students",
            "courses",
            "enrollments",
        }
        # Moodle ingestion (0003) and Phase 1 (0002) tables are untouched.
        assert set(inspect(db_engine).get_table_names(schema="academic")) == PHASE1_ACADEMIC_TABLES
        assert (
            set(inspect(db_engine).get_table_names(schema="raw_moodle"))
            == PHASE1_RAW_MOODLE_TABLES
        )
    finally:
        command.upgrade(cfg, "head")

    assert set(inspect(db_engine).get_table_names(schema="raw_moodle")) == RAW_MOODLE_TABLES


def test_downgrade_to_0002_removes_moodle_and_attendance_ingestion(db_engine: Engine) -> None:
    cfg = alembic_config()

    try:
        command.downgrade(cfg, "0002_academic_data_foundation")
        assert inspect(db_engine).get_table_names(schema="raw_moodle") == []
        assert inspect(db_engine).get_table_names(schema="raw_attendance") == []
        assert inspect(db_engine).get_table_names(schema="staging") == []
        # Phase 1 tables are untouched by these migrations' downgrade.
        assert set(inspect(db_engine).get_table_names(schema="academic")) == PHASE1_ACADEMIC_TABLES
        assert (
            set(inspect(db_engine).get_table_names(schema="integration"))
            == PHASE1_INTEGRATION_TABLES
        )
    finally:
        command.upgrade(cfg, "head")

    assert set(inspect(db_engine).get_table_names(schema="raw_moodle")) == RAW_MOODLE_TABLES
    assert set(inspect(db_engine).get_table_names(schema="raw_attendance")) == RAW_ATTENDANCE_TABLES


def test_upgrade_head_twice_is_safe() -> None:
    cfg = alembic_config()

    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
