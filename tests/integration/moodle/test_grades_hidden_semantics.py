"""Moodle's `hidden` semantics through extraction and staging.

mdl_grade_items.hidden / mdl_grade_grades.hidden: 0 is visible, 1 is
hidden always, any larger value is a Unix timestamp meaning "hidden
until" (Moodle: grade_object::is_hidden). Extraction applies that rule
(app.integration.moodle.grades_source.is_moodle_hidden) and staging
excludes whatever is hidden at the snapshot — staging itself is unchanged.

Every test passes an explicit reference time, so nothing here depends on
the wall clock (except the one test that exercises the default).
"""

import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text

from app.integration.moodle.grades_source import extract_moodle_grades_batch
from app.integration.moodle.grades_staging_writer import write_staging_grades_batch
from app.integration.moodle.models.grades_staging import StagingGradeItem, StagingStudentGrade
from tests.integration.moodle.fake_moodle import (
    insert_course,
    insert_grade_grade,
    insert_grade_item,
)

REFERENCE = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
NOW = int(REFERENCE.timestamp())
FUTURE = NOW + 86_400
PAST = NOW - 86_400

GradeKey = tuple[str, str]  # (grade_item_source_id, student_source_id)


def _stage(
    moodle_engine: Engine,
    app_engine: Engine,
    moodle_course_id: int,
    reference_time: datetime | None = REFERENCE,
) -> tuple[set[str], dict[GradeKey, Decimal | None]]:
    """Extract from the fake Moodle and stage; returns the staged grade
    item source ids and the staged grades keyed by (item, student).
    """
    extraction = extract_moodle_grades_batch(moodle_engine, moodle_course_id, reference_time)
    with app_engine.begin() as connection:
        issues = write_staging_grades_batch(connection, uuid.uuid4(), moodle_course_id, extraction)
    assert issues == []
    with app_engine.connect() as connection:
        items = set(connection.execute(select(StagingGradeItem.source_id)).scalars())
        grades = {
            (row.grade_item_source_id, row.student_source_id): row.grade
            for row in connection.execute(
                select(
                    StagingStudentGrade.grade_item_source_id,
                    StagingStudentGrade.student_source_id,
                    StagingStudentGrade.grade,
                )
            )
        }
    return items, grades


def _item_with_grade(
    moodle_engine: Engine, *, item_hidden: int, grade_hidden: int = 0
) -> tuple[int, int]:
    """One course with one item and one student grade. Returns (course_id, item_id)."""
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Course")
        item_id = insert_grade_item(connection, courseid=course_id, hidden=item_hidden)
        insert_grade_grade(connection, itemid=item_id, userid=3, finalgrade=30, hidden=grade_hidden)
    return course_id, item_id


# -- extraction: the four cases, for the item and for the student grade ----


@pytest.mark.parametrize(
    ("hidden", "expected"),
    [(0, False), (1, True), (FUTURE, True), (PAST, False)],
    ids=["zero-visible", "one-hidden", "future-timestamp-hidden", "past-timestamp-visible"],
)
def test_grade_item_hidden_is_extracted_with_moodle_semantics(
    moodle_engine: Engine, hidden: int, expected: bool
) -> None:
    course_id, _ = _item_with_grade(moodle_engine, item_hidden=hidden)

    result = extract_moodle_grades_batch(moodle_engine, course_id, REFERENCE)

    assert result.grade_items[0].hidden is expected


@pytest.mark.parametrize(
    ("hidden", "expected"),
    [(0, False), (1, True), (FUTURE, True), (PAST, False)],
    ids=["zero-visible", "one-hidden", "future-timestamp-hidden", "past-timestamp-visible"],
)
def test_student_grade_hidden_is_extracted_with_moodle_semantics(
    moodle_engine: Engine, hidden: int, expected: bool
) -> None:
    course_id, _ = _item_with_grade(moodle_engine, item_hidden=0, grade_hidden=hidden)

    result = extract_moodle_grades_batch(moodle_engine, course_id, REFERENCE)

    assert result.student_grades[0].hidden is expected


def test_default_reference_time_is_the_snapshot_time(moodle_engine: Engine) -> None:
    """Without an explicit reference time, "now" is the Moodle snapshot
    instant: an hour ago is visible, an hour ahead is hidden.
    """
    now = int(time.time())
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Course")
        insert_grade_item(connection, courseid=course_id, itemname="Past", hidden=now - 3600)
        insert_grade_item(connection, courseid=course_id, itemname="Future", hidden=now + 3600)

    result = extract_moodle_grades_batch(moodle_engine, course_id)

    assert {i.name: i.hidden for i in result.grade_items} == {"Past": False, "Future": True}


# -- pipeline: what reaches staging ----------------------------------------


def test_visible_item_with_visible_grade_reaches_staging(
    moodle_engine: Engine, app_engine: Engine
) -> None:
    course_id, item_id = _item_with_grade(moodle_engine, item_hidden=0)

    items, grades = _stage(moodle_engine, app_engine, course_id)

    assert items == {str(item_id)}
    assert grades == {(str(item_id), "3"): Decimal("30")}


def test_permanently_hidden_item_is_excluded_with_its_grades(
    moodle_engine: Engine, app_engine: Engine
) -> None:
    course_id, _ = _item_with_grade(moodle_engine, item_hidden=1)

    items, grades = _stage(moodle_engine, app_engine, course_id)

    assert items == set()
    assert grades == {}


def test_future_hidden_item_is_excluded_with_its_grades(
    moodle_engine: Engine, app_engine: Engine
) -> None:
    course_id, _ = _item_with_grade(moodle_engine, item_hidden=FUTURE)

    items, grades = _stage(moodle_engine, app_engine, course_id)

    assert items == set()
    assert grades == {}


def test_past_hidden_item_is_included_with_its_grades(
    moodle_engine: Engine, app_engine: Engine
) -> None:
    course_id, item_id = _item_with_grade(moodle_engine, item_hidden=PAST)

    items, grades = _stage(moodle_engine, app_engine, course_id)

    assert items == {str(item_id)}
    assert grades == {(str(item_id), "3"): Decimal("30")}


@pytest.mark.parametrize("grade_hidden", [1, FUTURE], ids=["hidden-always", "hidden-until-future"])
def test_hidden_individual_grade_is_excluded_even_when_the_item_is_visible(
    moodle_engine: Engine, app_engine: Engine, grade_hidden: int
) -> None:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Course")
        item_id = insert_grade_item(connection, courseid=course_id, hidden=0)
        insert_grade_grade(connection, itemid=item_id, userid=3, finalgrade=30, hidden=grade_hidden)
        insert_grade_grade(connection, itemid=item_id, userid=4, finalgrade=40, hidden=0)

    items, grades = _stage(moodle_engine, app_engine, course_id)

    assert items == {str(item_id)}
    assert grades == {(str(item_id), "4"): Decimal("40")}


def test_past_hidden_individual_grade_is_included(
    moodle_engine: Engine, app_engine: Engine
) -> None:
    course_id, item_id = _item_with_grade(moodle_engine, item_hidden=0, grade_hidden=PAST)

    _, grades = _stage(moodle_engine, app_engine, course_id)

    assert grades == {(str(item_id), "3"): Decimal("30")}


@pytest.mark.parametrize("item_hidden", [1, FUTURE], ids=["hidden-always", "hidden-until-future"])
def test_visible_grade_under_a_hidden_item_is_excluded(
    moodle_engine: Engine, app_engine: Engine, item_hidden: int
) -> None:
    course_id, _ = _item_with_grade(moodle_engine, item_hidden=item_hidden, grade_hidden=0)

    _, grades = _stage(moodle_engine, app_engine, course_id)

    assert grades == {}


def test_a_hidden_until_item_appears_once_its_time_has_passed(
    moodle_engine: Engine, app_engine: Engine
) -> None:
    """The same Moodle data, staged at two instants: excluded while the
    "hidden until" time is in the future, included after it.
    """
    course_id, item_id = _item_with_grade(moodle_engine, item_hidden=NOW + 3600)

    before_items, before_grades = _stage(moodle_engine, app_engine, course_id, REFERENCE)
    after_items, after_grades = _stage(
        moodle_engine, app_engine, course_id, datetime.fromtimestamp(NOW + 7200, tz=UTC)
    )

    assert (before_items, before_grades) == (set(), {})
    assert after_items == {str(item_id)}
    assert after_grades == {(str(item_id), "3"): Decimal("30")}


# -- regression: the production case ---------------------------------------

PRODUCTION_HIDDEN_UNTIL = 1790737200  # 2026-09-30T03:00:00Z
PRODUCTION_TIMEMODIFIED = 1790655026
EXAM_NAME = "Examen 1 Administración de la Configuración, Métricas y Riesgos"
EXAM_GRADES = {  # userid -> finalgrade; two users have no grade yet (NULL)
    3: "66.66667",
    4: "83.33333",
    5: "100",
    6: None,
    7: "86.66667",
    8: "96.66667",
    9: "96.66667",
    10: None,
    11: "90",
    12: "80",
    13: "86.66667",
    14: "66.66667",
    15: "96.66667",
    16: "90",
}


def _seed_production_shaped_course(moodle_engine: Engine) -> int:
    """Three ordinary assignments, plus a quiz with id 8 whose own hidden
    value is a "hidden until" timestamp while every student grade under
    it is individually visible (hidden = 0).
    """
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Production-shaped course")
        for name in ("Tarea 01", "Tarea 02", "Tarea 03"):
            insert_grade_item(connection, courseid=course_id, itemname=name)
        connection.execute(
            text("""
                INSERT INTO mdl_grade_items
                    (id, courseid, itemtype, itemmodule, itemname, grademax, hidden, timemodified)
                VALUES (8, :course_id, 'mod', 'quiz', :name, 100, :hidden, :timemodified)
            """),
            {
                "course_id": course_id,
                "name": EXAM_NAME,
                "hidden": PRODUCTION_HIDDEN_UNTIL,
                "timemodified": PRODUCTION_TIMEMODIFIED,
            },
        )
        for user_id, grade in EXAM_GRADES.items():
            insert_grade_grade(
                connection,
                itemid=8,
                userid=user_id,
                finalgrade=float(grade) if grade is not None else None,
                hidden=0,
            )
    return course_id


def test_production_quiz_hidden_until_a_past_timestamp_is_not_excluded(
    moodle_engine: Engine, app_engine: Engine
) -> None:
    course_id = _seed_production_shaped_course(moodle_engine)
    after_the_timestamp = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)

    items, grades = _stage(moodle_engine, app_engine, course_id, after_the_timestamp)

    assert "8" in items
    exam_grades = {student: grade for (item, student), grade in grades.items() if item == "8"}
    assert set(exam_grades) == {str(user_id) for user_id in EXAM_GRADES}  # all 14 flow through
    assert exam_grades["3"] == Decimal("66.66667")
    assert exam_grades["5"] == Decimal("100")
    # Not graded yet stays NULL all the way — it never becomes a zero.
    assert exam_grades["6"] is None and exam_grades["10"] is None
    assert sum(1 for grade in exam_grades.values() if grade is None) == 2
    with app_engine.connect() as connection:
        staged = connection.execute(
            select(
                StagingGradeItem.name, StagingGradeItem.itemmodule, StagingGradeItem.max_grade
            ).where(StagingGradeItem.source_id == "8")
        ).one()
    assert (staged.name, staged.itemmodule, staged.max_grade) == (EXAM_NAME, "quiz", 100)
    assert len(items) == 4  # the three ordinary assignments are unaffected


def test_the_same_production_quiz_is_still_hidden_before_its_timestamp(
    moodle_engine: Engine, app_engine: Engine
) -> None:
    course_id = _seed_production_shaped_course(moodle_engine)
    before_the_timestamp = datetime(2026, 9, 30, 2, 59, 59, tzinfo=UTC)

    items, grades = _stage(moodle_engine, app_engine, course_id, before_the_timestamp)

    assert "8" not in items
    assert not [key for key in grades if key[0] == "8"]
    assert len(items) == 3
