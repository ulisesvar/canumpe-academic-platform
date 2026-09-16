from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AttendanceSyncSettings(BaseSettings):
    """Configuration for the Attendance sync service only.

    Deliberately separate from app.core.config.Settings: the public API
    process must never load or hold Attendance credentials. Only the
    separately-invoked sync command (app.integration.attendance.sync)
    reads this class.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    attendance_db_url: str
    #: The Attendance source has no course id of its own. Attendance
    #: currently belongs to this one Moodle course, resolved through
    #: integration.course_sources (source_system="moodle") — never a
    #: hardcoded academic.courses.id.
    attendance_moodle_course_id: int


@lru_cache
def get_attendance_sync_settings() -> AttendanceSyncSettings:
    # pydantic-settings populates required fields from the environment at
    # runtime; mypy has no way to see that without the pydantic plugin.
    return AttendanceSyncSettings()  # type: ignore[call-arg]
