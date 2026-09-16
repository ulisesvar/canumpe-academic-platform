from collections.abc import Generator

import pytest
from sqlalchemy import Engine

from tests.integration.attendance.fake_attendance import (
    create_fake_attendance_schema,
    truncate_attendance_pipeline_tables,
    truncate_fake_attendance_schema,
)


@pytest.fixture(scope="session", autouse=True)
def _fake_attendance_schema(db_engine: Engine) -> None:
    create_fake_attendance_schema(db_engine)


@pytest.fixture(autouse=True)
def _clean_attendance_pipeline_state(db_engine: Engine) -> Generator[None, None, None]:
    """Every test in this package starts from a fully empty slate.

    Unlike the ORM `db_session` fixture used elsewhere, the Attendance
    pipeline commits real transactions (that's the point — it must
    survive partway failures the way production does), so cleanup here
    is a real TRUNCATE rather than a rolled-back SAVEPOINT.
    """
    truncate_fake_attendance_schema(db_engine)
    truncate_attendance_pipeline_tables(db_engine)
    yield


@pytest.fixture
def attendance_engine(db_engine: Engine) -> Engine:
    """The same test database, standing in for a separate Attendance server."""
    return db_engine


@pytest.fixture
def app_engine(db_engine: Engine) -> Engine:
    return db_engine
