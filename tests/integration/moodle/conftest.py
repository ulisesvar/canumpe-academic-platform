from collections.abc import Generator

import pytest
from sqlalchemy import Engine

from tests.integration.moodle.fake_moodle import (
    create_fake_moodle_schema,
    truncate_fake_moodle_schema,
    truncate_pipeline_tables,
)


@pytest.fixture(scope="session", autouse=True)
def _fake_moodle_schema(db_engine: Engine) -> None:
    create_fake_moodle_schema(db_engine)


@pytest.fixture(autouse=True)
def _clean_moodle_pipeline_state(db_engine: Engine) -> Generator[None, None, None]:
    """Every test in this package starts from a fully empty slate.

    Unlike the ORM `db_session` fixture used elsewhere, the Moodle
    pipeline commits real transactions (that's the point — it must
    survive partway failures the way production does), so cleanup here
    is a real TRUNCATE rather than a rolled-back SAVEPOINT.
    """
    truncate_fake_moodle_schema(db_engine)
    truncate_pipeline_tables(db_engine)
    yield


@pytest.fixture
def moodle_engine(db_engine: Engine) -> Engine:
    """The same test database, standing in for a separate Moodle server.

    Extraction code only ever receives an Engine — it neither knows nor
    cares whether it is physically the same database as `app_engine` in
    tests, or a different server in production.
    """
    return db_engine


@pytest.fixture
def app_engine(db_engine: Engine) -> Engine:
    return db_engine
