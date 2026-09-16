import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine, inspect, select

from app.integration.attendance.models.raw import (
    RawAttendanceRecord,
    RawAttendanceSession,
    RawAttendanceStudent,
)
from app.integration.attendance.raw_writer import write_raw_batch
from app.integration.attendance.source import (
    AttendanceExtractionResult,
    ExtractedAttendanceRecord,
    ExtractedAttendanceSession,
    ExtractedAttendanceStudent,
)

SNAPSHOT_TIME = datetime.now(UTC)


def _extraction() -> AttendanceExtractionResult:
    return AttendanceExtractionResult(
        snapshot_time=SNAPSHOT_TIME,
        students=[ExtractedAttendanceStudent("11", "123456789", SNAPSHOT_TIME)],
        sessions=[ExtractedAttendanceSession("5", SNAPSHOT_TIME, None, "OPEN")],
        attendances=[ExtractedAttendanceRecord("900", "11", "5", SNAPSHOT_TIME)],
    )


def test_raw_students_written(app_engine: Engine) -> None:
    with app_engine.begin() as connection:
        write_raw_batch(connection, uuid.uuid4(), _extraction())

    with app_engine.begin() as connection:
        rows = connection.execute(select(RawAttendanceStudent)).all()

    assert len(rows) == 1
    assert rows[0].source_id == "11"
    assert rows[0].account_number == "123456789"


def test_raw_sessions_written(app_engine: Engine) -> None:
    with app_engine.begin() as connection:
        write_raw_batch(connection, uuid.uuid4(), _extraction())

    with app_engine.begin() as connection:
        rows = connection.execute(select(RawAttendanceSession)).all()

    assert len(rows) == 1
    assert rows[0].source_id == "5"
    assert rows[0].status == "OPEN"


def test_raw_attendances_written(app_engine: Engine) -> None:
    with app_engine.begin() as connection:
        write_raw_batch(connection, uuid.uuid4(), _extraction())

    with app_engine.begin() as connection:
        rows = connection.execute(select(RawAttendanceRecord)).all()

    assert len(rows) == 1
    assert rows[0].source_id == "900"
    assert rows[0].student_source_id == "11"
    assert rows[0].session_source_id == "5"


def _raw_attendance_columns(app_engine: Engine) -> set[str]:
    return {
        c["name"] for c in inspect(app_engine).get_columns("attendances", schema="raw_attendance")
    }


def test_no_latitude_column_in_raw_attendance(app_engine: Engine) -> None:
    assert "latitude" not in _raw_attendance_columns(app_engine)


def test_no_longitude_column_in_raw_attendance(app_engine: Engine) -> None:
    assert "longitude" not in _raw_attendance_columns(app_engine)


def test_no_distance_column_in_raw_attendance(app_engine: Engine) -> None:
    assert "distance_meters" not in _raw_attendance_columns(app_engine)
