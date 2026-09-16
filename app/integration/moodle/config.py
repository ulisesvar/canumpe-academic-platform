from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class MoodleSyncSettings(BaseSettings):
    """Configuration for the Moodle sync service only.

    Deliberately separate from app.core.config.Settings: the public API
    process must never load or hold Moodle credentials. Only the
    separately-invoked sync command (app.integration.moodle.sync) reads
    this class.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    moodle_db_url: str
    moodle_course_id: int


@lru_cache
def get_moodle_sync_settings() -> MoodleSyncSettings:
    # pydantic-settings populates required fields from the environment at
    # runtime; mypy has no way to see that without the pydantic plugin.
    return MoodleSyncSettings()  # type: ignore[call-arg]
