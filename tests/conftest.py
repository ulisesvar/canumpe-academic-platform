import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core.config import get_settings
from app.main import app

TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://canumpe_test:canumpe_test@127.0.0.1:5433/canumpe_test",
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def alembic_config() -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return cfg


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(TEST_DATABASE_URL)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema() -> Generator[None, None, None]:
    """Ensures the test database is at Alembic head before any test runs.

    Tests that exercise migration behavior itself (downgrade/upgrade
    cycles) are responsible for leaving the database back at head when
    they finish.
    """
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    get_settings.cache_clear()
    command.upgrade(alembic_config(), "head")
    yield
    get_settings.cache_clear()


@pytest.fixture
def db_session(db_engine: Engine) -> Generator[Session, None, None]:
    """A session whose changes are always rolled back after the test.

    Uses SQLAlchemy 2.0's "join an external transaction" pattern: an outer
    transaction is opened on a dedicated connection, and the session joins
    it via a SAVEPOINT so that a test's own session.commit()/rollback()
    calls (including ones triggered by an expected IntegrityError) don't
    end the outer transaction early.
    """
    connection = db_engine.connect()
    outer_transaction = connection.begin()
    session_factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()
