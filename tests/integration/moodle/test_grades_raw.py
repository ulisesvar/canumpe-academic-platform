import dataclasses
import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine, inspect, select

from app.integration.moodle.grades_raw_writer import write_raw_grades_batch
from app.integration.moodle.grades_source import (
    ExtractedGradeItem,
    ExtractedStudentGrade,
    MoodleGradesExtractionResult,
)
from app.integration.moodle.models.grades_raw import RawMoodleGradeItem, RawMoodleStudentGrade

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


def test_raw_grade_items_written(app_engine: Engine) -> None:
    with app_engine.begin() as connection:
        write_raw_grades_batch(connection, uuid.uuid4(), MOODLE_COURSE_ID, _extraction())

    with app_engine.begin() as connection:
        rows = connection.execute(select(RawMoodleGradeItem)).all()

    assert len(rows) == 1
    assert rows[0].source_id == "5"
    assert rows[0].name == "Tarea 01"
    assert rows[0].course_source_id == str(MOODLE_COURSE_ID)


def test_raw_student_grades_written(app_engine: Engine) -> None:
    with app_engine.begin() as connection:
        write_raw_grades_batch(connection, uuid.uuid4(), MOODLE_COURSE_ID, _extraction())

    with app_engine.begin() as connection:
        rows = connection.execute(select(RawMoodleStudentGrade)).all()

    assert len(rows) == 1
    assert rows[0].source_id == "900"
    assert rows[0].grade_item_source_id == "5"
    assert rows[0].student_source_id == "3"
    assert rows[0].grade == 30


def test_raw_hashes_are_deterministic(app_engine: Engine) -> None:
    with app_engine.begin() as connection:
        write_raw_grades_batch(connection, uuid.uuid4(), MOODLE_COURSE_ID, _extraction())
    with app_engine.begin() as connection:
        first_item = connection.execute(select(RawMoodleGradeItem)).one()
        first_grade = connection.execute(select(RawMoodleStudentGrade)).one()

    with app_engine.begin() as connection:
        write_raw_grades_batch(connection, uuid.uuid4(), MOODLE_COURSE_ID, _extraction())
    with app_engine.begin() as connection:
        rows_items = connection.execute(select(RawMoodleGradeItem)).all()
        rows_grades = connection.execute(select(RawMoodleStudentGrade)).all()

    second_item = next(r for r in rows_items if r.id != first_item.id)
    second_grade = next(r for r in rows_grades if r.id != first_grade.id)
    assert second_item.source_hash == first_item.source_hash
    assert second_grade.source_hash == first_grade.source_hash


def test_changed_grade_changes_hash(app_engine: Engine) -> None:
    with app_engine.begin() as connection:
        write_raw_grades_batch(connection, uuid.uuid4(), MOODLE_COURSE_ID, _extraction())
    with app_engine.begin() as connection:
        original = connection.execute(select(RawMoodleStudentGrade)).one()

    changed = _extraction(
        student_grades=[ExtractedStudentGrade("900", "5", "3", 80, False, SNAPSHOT_TIME)]
    )
    with app_engine.begin() as connection:
        write_raw_grades_batch(connection, uuid.uuid4(), MOODLE_COURSE_ID, changed)
    with app_engine.begin() as connection:
        rows = connection.execute(select(RawMoodleStudentGrade)).all()

    updated = next(r for r in rows if r.id != original.id)
    assert updated.source_hash != original.source_hash


def _raw_grade_item_columns(app_engine: Engine) -> set[str]:
    return {c["name"] for c in inspect(app_engine).get_columns("grade_items", schema="raw_moodle")}


def _raw_student_grade_columns(app_engine: Engine) -> set[str]:
    return {
        c["name"] for c in inspect(app_engine).get_columns("student_grades", schema="raw_moodle")
    }


def test_unnecessary_gradebook_fields_are_not_stored(app_engine: Engine) -> None:
    forbidden = {
        "rawgrade",
        "rawgrademin",
        "rawgrademax",
        "feedback",
        "information",
        "overridden",
        "excluded",
        "aggregationweight",
        "outcomeid",
        "scaleid",
    }
    item_field_names = {f.name for f in dataclasses.fields(ExtractedGradeItem)}
    grade_field_names = {f.name for f in dataclasses.fields(ExtractedStudentGrade)}

    assert not (item_field_names & forbidden)
    assert not (grade_field_names & forbidden)
    assert not (_raw_grade_item_columns(app_engine) & forbidden)
    assert not (_raw_student_grade_columns(app_engine) & forbidden)
