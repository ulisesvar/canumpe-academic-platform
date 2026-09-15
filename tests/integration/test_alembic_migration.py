from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from app.core.config import get_settings
from tests.conftest import TEST_DATABASE_URL

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_alembic_upgrades_empty_database_to_head(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    get_settings.cache_clear()

    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))

    try:
        command.upgrade(alembic_cfg, "head")
    finally:
        get_settings.cache_clear()

    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as connection:
            table_names = inspect(connection).get_table_names()
    finally:
        engine.dispose()

    assert "alembic_version" in table_names
