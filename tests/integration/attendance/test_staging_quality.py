import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine

from app.integration.attendance.source import (
    AttendanceExtractionResult,
    ExtractedAttendanceRecord,
    ExtractedAttendanceSession,
    ExtractedAttendanceStudent,
)
from app.integration.attendance.staging_writer import write_staging_batch
from app.integration.attendance.validation import validate_staged_batch
from tests.integration.attendance.helpers import seed_academic_student, seed_moodle_course_mapping

SNAPSHOT_TIME = datetime.now(UTC)
MOODLE_COURSE_ID = 2


def _extraction(**overrides: object) -> AttendanceExtractionResult:
    defaults = {
        "snapshot_time": SNAPSHOT_TIME,
        "students": [ExtractedAttendanceStudent("11", "1001", SNAPSHOT_TIME)],
        "sessions": [ExtractedAttendanceSession("5", SNAPSHOT_TIME, None, "OPEN")],
        "attendances": [ExtractedAttendanceRecord("900", "11", "5", SNAPSHOT_TIME)],
    }
    defaults.update(overrides)
    return AttendanceExtractionResult(**defaults)  # type: ignore[arg-type]


def test_valid_batch_passes(app_engine: Engine) -> None:
    seed_academic_student(app_engine, account_number="1001")
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)

    with app_engine.begin() as connection:
        staging_issues = write_staging_batch(connection, uuid.uuid4(), _extraction())
    with app_engine.begin() as connection:
        validation_issues = validate_staged_batch(connection, MOODLE_COURSE_ID)

    assert staging_issues == []
    assert validation_issues == []


def test_missing_student_reference_fails(app_engine: Engine) -> None:
    seed_academic_student(app_engine, account_number="1001")
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    extraction = _extraction(
        attendances=[ExtractedAttendanceRecord("900", "does-not-exist", "5", SNAPSHOT_TIME)]
    )

    with app_engine.begin() as connection:
        assert write_staging_batch(connection, uuid.uuid4(), extraction) == []
    with app_engine.begin() as connection:
        issues = validate_staged_batch(connection, MOODLE_COURSE_ID)

    assert any("unknown student_source_id" in issue for issue in issues)


def test_missing_session_reference_fails(app_engine: Engine) -> None:
    seed_academic_student(app_engine, account_number="1001")
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    extraction = _extraction(
        attendances=[ExtractedAttendanceRecord("900", "11", "does-not-exist", SNAPSHOT_TIME)]
    )

    with app_engine.begin() as connection:
        assert write_staging_batch(connection, uuid.uuid4(), extraction) == []
    with app_engine.begin() as connection:
        issues = validate_staged_batch(connection, MOODLE_COURSE_ID)

    assert any("unknown session_source_id" in issue for issue in issues)


def test_duplicate_session_student_attendance_fails(app_engine: Engine) -> None:
    seed_academic_student(app_engine, account_number="1001")
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    extraction = _extraction(
        attendances=[
            ExtractedAttendanceRecord("900", "11", "5", SNAPSHOT_TIME),
            ExtractedAttendanceRecord("901", "11", "5", SNAPSHOT_TIME),
        ]
    )

    with app_engine.begin() as connection:
        assert write_staging_batch(connection, uuid.uuid4(), extraction) == []
    with app_engine.begin() as connection:
        issues = validate_staged_batch(connection, MOODLE_COURSE_ID)

    assert any("duplicate attendance" in issue for issue in issues)
