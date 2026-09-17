import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine

from app.integration.moodle.grades_source import (
    ExtractedGradeItem,
    ExtractedStudentGrade,
    MoodleGradesExtractionResult,
)
from app.integration.moodle.grades_staging_writer import write_staging_grades_batch
from app.integration.moodle.grades_validation import validate_staged_grades_batch
from tests.integration.moodle.grades_helpers import seed_moodle_course_mapping

SNAPSHOT_TIME = datetime.now(UTC)
MOODLE_COURSE_ID = 2


def _extraction(**overrides: object) -> MoodleGradesExtractionResult:
    defaults: dict[str, object] = {
        "snapshot_time": SNAPSHOT_TIME,
        "grade_items": [ExtractedGradeItem("5", "Tarea 01", "assign", 100, False, SNAPSHOT_TIME)],
        "student_grades": [ExtractedStudentGrade("900", "5", "3", 30, False, SNAPSHOT_TIME)],
    }
    defaults.update(overrides)
    return MoodleGradesExtractionResult(**defaults)  # type: ignore[arg-type]


def test_valid_grade_item_passes(app_engine: Engine) -> None:
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)

    with app_engine.begin() as connection:
        staging_issues = write_staging_grades_batch(
            connection, uuid.uuid4(), MOODLE_COURSE_ID, _extraction()
        )
    with app_engine.begin() as connection:
        validation_issues = validate_staged_grades_batch(connection, MOODLE_COURSE_ID)

    assert staging_issues == []
    assert validation_issues == []


def test_missing_name_fails(app_engine: Engine) -> None:
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    extraction = _extraction(
        grade_items=[ExtractedGradeItem("5", None, "assign", 100, False, SNAPSHOT_TIME)]
    )

    with app_engine.begin() as connection:
        issues = write_staging_grades_batch(connection, uuid.uuid4(), MOODLE_COURSE_ID, extraction)

    assert any("missing name" in issue for issue in issues)


def test_invalid_max_grade_fails(app_engine: Engine) -> None:
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    extraction = _extraction(
        grade_items=[ExtractedGradeItem("5", "Tarea 01", "assign", 0, False, SNAPSHOT_TIME)]
    )

    with app_engine.begin() as connection:
        issues = write_staging_grades_batch(connection, uuid.uuid4(), MOODLE_COURSE_ID, extraction)

    assert any("invalid" in issue and "max_grade" in issue for issue in issues)


def test_broken_grade_item_reference_fails(app_engine: Engine) -> None:
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    extraction = _extraction(
        grade_items=[],
        student_grades=[ExtractedStudentGrade("900", "does-not-exist", "3", 30, False, None)],
    )

    with app_engine.begin() as connection:
        staging_issues = write_staging_grades_batch(
            connection, uuid.uuid4(), MOODLE_COURSE_ID, extraction
        )
        assert staging_issues == []
    with app_engine.begin() as connection:
        issues = validate_staged_grades_batch(connection, MOODLE_COURSE_ID)

    assert any("unknown grade_item_source_id" in issue for issue in issues)


def test_duplicate_grade_for_same_item_and_student_fails(app_engine: Engine) -> None:
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    extraction = _extraction(
        student_grades=[
            ExtractedStudentGrade("900", "5", "3", 30, False, SNAPSHOT_TIME),
            ExtractedStudentGrade("901", "5", "3", 80, False, SNAPSHOT_TIME),
        ]
    )

    with app_engine.begin() as connection:
        staging_issues = write_staging_grades_batch(
            connection, uuid.uuid4(), MOODLE_COURSE_ID, extraction
        )
        assert staging_issues == []
    with app_engine.begin() as connection:
        issues = validate_staged_grades_batch(connection, MOODLE_COURSE_ID)

    assert any("duplicate grade" in issue for issue in issues)


def test_missing_course_mapping_fails(app_engine: Engine) -> None:
    with app_engine.begin() as connection:
        staging_issues = write_staging_grades_batch(
            connection, uuid.uuid4(), MOODLE_COURSE_ID, _extraction()
        )
        assert staging_issues == []
    with app_engine.begin() as connection:
        issues = validate_staged_grades_batch(connection, MOODLE_COURSE_ID)

    assert any("no integration.course_sources mapping" in issue for issue in issues)


def test_hidden_grade_item_is_excluded_without_an_issue(app_engine: Engine) -> None:
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    extraction = _extraction(
        grade_items=[ExtractedGradeItem("5", "Tarea 01", "assign", 100, True, SNAPSHOT_TIME)],
        student_grades=[],
    )

    with app_engine.begin() as connection:
        issues = write_staging_grades_batch(connection, uuid.uuid4(), MOODLE_COURSE_ID, extraction)

    assert issues == []


def test_hidden_student_grade_is_excluded_without_an_issue(app_engine: Engine) -> None:
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    extraction = _extraction(
        student_grades=[ExtractedStudentGrade("900", "5", "3", 30, True, SNAPSHOT_TIME)]
    )

    with app_engine.begin() as connection:
        issues = write_staging_grades_batch(connection, uuid.uuid4(), MOODLE_COURSE_ID, extraction)

    assert issues == []


def test_grade_under_a_hidden_item_is_excluded_even_if_the_grade_itself_is_not_hidden(
    app_engine: Engine,
) -> None:
    """Moodle's own semantics: hiding the item hides every grade under
    it, regardless of the individual grade row's own hidden flag.
    """
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    extraction = _extraction(
        grade_items=[ExtractedGradeItem("5", "Tarea 01", "assign", 100, True, SNAPSHOT_TIME)],
        student_grades=[ExtractedStudentGrade("900", "5", "3", 30, False, SNAPSHOT_TIME)],
    )

    with app_engine.begin() as connection:
        issues = write_staging_grades_batch(connection, uuid.uuid4(), MOODLE_COURSE_ID, extraction)

    assert issues == []
