from sqlalchemy import Engine, inspect

EXPECTED_SCHEMAS = ("raw_moodle", "raw_attendance", "staging", "academic", "integration", "auth")


def test_all_six_schemas_exist(db_engine: Engine) -> None:
    existing = set(inspect(db_engine).get_schema_names())

    assert set(EXPECTED_SCHEMAS) <= existing
