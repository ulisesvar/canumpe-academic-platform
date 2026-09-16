import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine

from app.integration.moodle.source import (
    ExtractedCourse,
    ExtractedEnrollment,
    ExtractedStudent,
    MoodleExtractionResult,
)
from app.integration.moodle.staging_writer import write_staging_batch
from app.integration.moodle.validation import validate_staged_batch

SNAPSHOT_TIME = datetime.now(UTC)


def _extraction(**overrides: object) -> MoodleExtractionResult:
    defaults = {
        "snapshot_time": SNAPSHOT_TIME,
        "students": [ExtractedStudent("137", "1001", "Ada", "Lovelace", None, None)],
        "courses": [ExtractedCourse("2", "CS101", "Intro to Programming", True, None)],
        "enrollments": [ExtractedEnrollment("900", "137", "2", "active", None)],
    }
    defaults.update(overrides)
    return MoodleExtractionResult(**defaults)  # type: ignore[arg-type]


def test_valid_batch_passes(app_engine: Engine) -> None:
    with app_engine.begin() as connection:
        staging_issues = write_staging_batch(connection, uuid.uuid4(), _extraction())
    with app_engine.begin() as connection:
        validation_issues = validate_staged_batch(connection)

    assert staging_issues == []
    assert validation_issues == []


def test_missing_account_number_fails(app_engine: Engine) -> None:
    extraction = _extraction(
        students=[ExtractedStudent("137", "", "Ada", "Lovelace", None, None)]
    )

    with app_engine.begin() as connection:
        issues = write_staging_batch(connection, uuid.uuid4(), extraction)

    assert any("account_number" in issue for issue in issues)


def test_duplicate_account_number_fails(app_engine: Engine) -> None:
    extraction = _extraction(
        students=[
            ExtractedStudent("137", "1001", "Ada", "Lovelace", None, None),
            ExtractedStudent("138", "1001", "A.", "L.", None, None),
        ],
        enrollments=[
            ExtractedEnrollment("900", "137", "2", "active", None),
            ExtractedEnrollment("901", "138", "2", "active", None),
        ],
    )

    with app_engine.begin() as connection:
        assert write_staging_batch(connection, uuid.uuid4(), extraction) == []
    with app_engine.begin() as connection:
        issues = validate_staged_batch(connection)

    assert any("duplicate account_number" in issue for issue in issues)


def test_enrollment_referencing_unknown_student_fails(app_engine: Engine) -> None:
    extraction = _extraction(
        enrollments=[ExtractedEnrollment("900", "does-not-exist", "2", "active", None)]
    )

    with app_engine.begin() as connection:
        assert write_staging_batch(connection, uuid.uuid4(), extraction) == []
    with app_engine.begin() as connection:
        issues = validate_staged_batch(connection)

    assert any("unknown student_source_id" in issue for issue in issues)


def test_enrollment_referencing_unknown_course_fails(app_engine: Engine) -> None:
    extraction = _extraction(
        enrollments=[ExtractedEnrollment("900", "137", "does-not-exist", "active", None)]
    )

    with app_engine.begin() as connection:
        assert write_staging_batch(connection, uuid.uuid4(), extraction) == []
    with app_engine.begin() as connection:
        issues = validate_staged_batch(connection)

    assert any("unknown course_source_id" in issue for issue in issues)
