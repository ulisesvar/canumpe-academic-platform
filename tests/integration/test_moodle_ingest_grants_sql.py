"""Executes deploy/sql/academic_ingest_moodle_grants.example.sql against
a real PostgreSQL server to prove it is actually valid SQL.

tests/unit/test_moodle_grants_reference.py only ever checked substrings
in the file's text — that let a repeated SEQUENCE keyword in every
multi-sequence GRANT block (`GRANT USAGE ON SEQUENCE a, SEQUENCE b, ...`
— invalid; PostgreSQL's real grammar is `GRANT USAGE ON SEQUENCE a, b,
...`, the keyword appears once) pass CI and reach production. Text
matching can never catch a syntax error; only running the SQL can.

Runs against the disposable session-scoped `db_engine` (already migrated
to head by the `_migrated_schema` autouse fixture, so every schema/
table/sequence this file references already exists) using a throwaway
role name substituted for the real `academic_ingest_moodle`, so this can
run repeatedly without depending on, or leaving behind, any role sharing
the production name.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GRANTS_SQL_PATH = REPO_ROOT / "deploy" / "sql" / "academic_ingest_moodle_grants.example.sql"

#: Never the real role name — this is created and dropped by this test alone.
TEST_ROLE = "test_academic_ingest_moodle_grants_check"

REQUIRED_SEQUENCE_USAGE = (
    "raw_moodle.grade_items_id_seq",
    "staging.grade_items_id_seq",
    "integration.grade_item_sources_id_seq",
    "academic.grade_items_id_seq",
)


def _grants_statements() -> list[str]:
    """Strips full-line comments and splits the file into individual
    statements on ';', substituting the disposable test role name for
    the production one. Every comment in this file is a standalone line
    (never trailing after SQL), so line-based stripping is sufficient.
    """
    raw = GRANTS_SQL_PATH.read_text().replace("academic_ingest_moodle", TEST_ROLE)
    body = "\n".join(
        line for line in raw.splitlines() if not line.strip().startswith("--")
    )
    return [statement.strip() for statement in body.split(";") if statement.strip()]


def _role_exists(engine: Engine, name: str) -> bool:
    with engine.connect() as connection:
        return (
            connection.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": name}
            ).scalar_one_or_none()
            is not None
        )


def _drop_test_role(engine: Engine) -> None:
    if not _role_exists(engine, TEST_ROLE):
        return
    with engine.begin() as connection:
        # DROP OWNED BY revokes every privilege (ACL entry) granted to the
        # role in this database — a plain DROP ROLE fails otherwise,
        # since the file grants it privileges on several tables/sequences.
        connection.execute(text(f"DROP OWNED BY {TEST_ROLE}"))
        connection.execute(text(f"DROP ROLE {TEST_ROLE}"))


@pytest.fixture
def clean_test_role(db_engine: Engine) -> Iterator[None]:
    _drop_test_role(db_engine)
    try:
        yield
    finally:
        _drop_test_role(db_engine)


def test_grants_reference_sql_executes_without_a_syntax_error(
    db_engine: Engine, clean_test_role: None
) -> None:
    with db_engine.begin() as connection:
        for statement in _grants_statements():
            try:
                connection.execute(text(statement))
            except Exception as exc:
                raise AssertionError(
                    f"grants reference SQL failed to execute:\n{statement}\n\n{exc}"
                ) from exc


def test_grants_reference_sql_actually_grants_sequence_usage(
    db_engine: Engine, clean_test_role: None
) -> None:
    with db_engine.begin() as connection:
        for statement in _grants_statements():
            connection.execute(text(statement))

    with db_engine.connect() as connection:
        for sequence in REQUIRED_SEQUENCE_USAGE:
            has_usage = connection.execute(
                text("SELECT has_sequence_privilege(:role, :sequence, 'USAGE')"),
                {"role": TEST_ROLE, "sequence": sequence},
            ).scalar_one()
            assert has_usage, f"{TEST_ROLE} is missing USAGE on {sequence}"
