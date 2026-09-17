"""Every Phase 5 API test commits real rows directly to academic.* — the
API's own DB session (app.db.session, a separate engine/connection pool
from the `db_session` SAVEPOINT-rollback fixture used elsewhere) would
never see uncommitted data on another connection. Truncate before each
test in this package for isolation, matching the established convention
in tests/integration/moodle and tests/integration/attendance.
"""

from collections.abc import Generator

import pytest
from sqlalchemy import Engine, text

ACADEMIC_TABLES = (
    "academic.student_grades",
    "academic.grade_items",
    "academic.attendance_records",
    "academic.attendance_sessions",
    "academic.enrollments",
    "academic.courses",
    "academic.students",
)


@pytest.fixture(autouse=True)
def _clean_academic_tables(db_engine: Engine) -> Generator[None, None, None]:
    tables = ", ".join(ACADEMIC_TABLES)
    with db_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    yield
