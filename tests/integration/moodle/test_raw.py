import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine, select

from app.integration.moodle.hashing import student_hash
from app.integration.moodle.models.raw import RawMoodleCourse, RawMoodleEnrollment, RawMoodleStudent
from app.integration.moodle.raw_writer import write_raw_batch
from app.integration.moodle.source import (
    ExtractedCourse,
    ExtractedEnrollment,
    ExtractedStudent,
    MoodleExtractionResult,
)

SNAPSHOT_TIME = datetime.now(UTC)


def _extraction(**overrides: object) -> MoodleExtractionResult:
    defaults = {
        "snapshot_time": SNAPSHOT_TIME,
        "students": [
            ExtractedStudent("137", "1001", "Ada", "Lovelace", "ada@example.com", None),
        ],
        "courses": [
            ExtractedCourse("2", "CS101", "Intro to Programming", True, None),
        ],
        "enrollments": [
            ExtractedEnrollment("900", "137", "2", "active", None),
        ],
    }
    defaults.update(overrides)
    return MoodleExtractionResult(**defaults)  # type: ignore[arg-type]


def test_students_land_in_raw_moodle_students(app_engine: Engine) -> None:
    batch_id = uuid.uuid4()
    with app_engine.begin() as connection:
        write_raw_batch(connection, batch_id, _extraction())

    with app_engine.begin() as connection:
        rows = connection.execute(select(RawMoodleStudent)).all()

    assert len(rows) == 1
    assert rows[0].source_id == "137"
    assert rows[0].account_number == "1001"


def test_courses_land_in_raw_moodle_courses(app_engine: Engine) -> None:
    batch_id = uuid.uuid4()
    with app_engine.begin() as connection:
        write_raw_batch(connection, batch_id, _extraction())

    with app_engine.begin() as connection:
        rows = connection.execute(select(RawMoodleCourse)).all()

    assert len(rows) == 1
    assert rows[0].source_id == "2"
    assert rows[0].name == "Intro to Programming"


def test_enrollments_land_in_raw_moodle_enrollments(app_engine: Engine) -> None:
    batch_id = uuid.uuid4()
    with app_engine.begin() as connection:
        write_raw_batch(connection, batch_id, _extraction())

    with app_engine.begin() as connection:
        rows = connection.execute(select(RawMoodleEnrollment)).all()

    assert len(rows) == 1
    assert rows[0].source_id == "900"
    assert rows[0].student_source_id == "137"
    assert rows[0].course_source_id == "2"


def test_batch_id_is_recorded_on_every_raw_row(app_engine: Engine) -> None:
    batch_id = uuid.uuid4()
    with app_engine.begin() as connection:
        write_raw_batch(connection, batch_id, _extraction())

    with app_engine.begin() as connection:
        student_batch_ids = connection.execute(select(RawMoodleStudent.batch_id)).scalars().all()
        course_batch_ids = connection.execute(select(RawMoodleCourse.batch_id)).scalars().all()
        enrollment_batch_ids = (
            connection.execute(select(RawMoodleEnrollment.batch_id)).scalars().all()
        )

    assert student_batch_ids == [batch_id]
    assert course_batch_ids == [batch_id]
    assert enrollment_batch_ids == [batch_id]


def test_raw_student_hash_matches_the_hashing_function(app_engine: Engine) -> None:
    batch_id = uuid.uuid4()
    with app_engine.begin() as connection:
        write_raw_batch(connection, batch_id, _extraction())

    with app_engine.begin() as connection:
        stored_hash = connection.execute(select(RawMoodleStudent.source_hash)).scalar_one()

    assert stored_hash == student_hash("1001", "Ada", "Lovelace", "ada@example.com")


def test_raw_student_hash_changes_when_source_content_changes(app_engine: Engine) -> None:
    with app_engine.begin() as connection:
        write_raw_batch(connection, uuid.uuid4(), _extraction())
    with app_engine.begin() as connection:
        first_hash = connection.execute(select(RawMoodleStudent.source_hash)).scalar_one()

    changed_extraction = _extraction(
        students=[ExtractedStudent("137", "1001", "Ada", "Lovelace-Byron", "ada@example.com", None)]
    )
    with app_engine.begin() as connection:
        write_raw_batch(connection, uuid.uuid4(), changed_extraction)
    with app_engine.begin() as connection:
        second_hash = connection.execute(
            select(RawMoodleStudent.source_hash).where(
                RawMoodleStudent.last_name == "Lovelace-Byron"
            )
        ).scalar_one()

    assert first_hash != second_hash
