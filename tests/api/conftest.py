"""Every Phase 5/6 API test commits real rows directly to academic.*/
auth.api_keys — the API's own DB session (app.db.session, a separate
engine/connection pool from the `db_session` SAVEPOINT-rollback fixture
used elsewhere) would never see uncommitted data on another connection.
Truncate before each test in this package for isolation, matching the
established convention in tests/integration/moodle and
tests/integration/attendance.
"""

from collections.abc import Generator

import pytest
from sqlalchemy import Engine, text

from tests.api.helpers import issue_test_admin_key

TABLES_TO_TRUNCATE = (
    "auth.api_keys",
    "academic.student_grades",
    "academic.grade_items",
    "academic.attendance_records",
    "academic.attendance_sessions",
    "academic.enrollments",
    "academic.courses",
    "academic.students",
)


@pytest.fixture(autouse=True)
def _clean_tables(db_engine: Engine) -> Generator[None, None, None]:
    tables = ", ".join(TABLES_TO_TRUNCATE)
    with db_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def admin_headers(db_engine: Engine) -> dict[str, str]:
    """An ADMIN API key, as a ready-to-use X-API-Key header — every
    /students/{student_id}/* request needs one since Phase 6.
    """
    key = issue_test_admin_key(db_engine)
    return {"X-API-Key": key}
