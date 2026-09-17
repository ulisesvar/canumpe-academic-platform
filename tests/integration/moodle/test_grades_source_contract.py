from sqlalchemy import Engine

from app.integration.moodle.grades_source import extract_moodle_grades_batch
from tests.integration.moodle.fake_moodle import (
    insert_course,
    insert_grade_grade,
    insert_grade_item,
)


def test_only_mod_grade_items_are_selected(moodle_engine: Engine) -> None:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        insert_grade_item(connection, courseid=course_id, itemtype="mod", itemname="Tarea 01")

    result = extract_moodle_grades_batch(moodle_engine, course_id)

    assert len(result.grade_items) == 1
    assert result.grade_items[0].name == "Tarea 01"


def test_course_total_item_is_excluded(moodle_engine: Engine) -> None:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        insert_grade_item(connection, courseid=course_id, itemtype="course", itemname=None)
        insert_grade_item(connection, courseid=course_id, itemtype="mod", itemname="Tarea 01")

    result = extract_moodle_grades_batch(moodle_engine, course_id)

    assert len(result.grade_items) == 1
    assert result.grade_items[0].name == "Tarea 01"


def test_grade_item_name_is_extracted(moodle_engine: Engine) -> None:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        insert_grade_item(
            connection,
            courseid=course_id,
            itemname="Tarea 01 — Identificación de Configuration Items",
        )

    result = extract_moodle_grades_batch(moodle_engine, course_id)

    assert result.grade_items[0].name == "Tarea 01 — Identificación de Configuration Items"


def test_grademax_is_extracted(moodle_engine: Engine) -> None:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        insert_grade_item(connection, courseid=course_id, grademax=100)

    result = extract_moodle_grades_batch(moodle_engine, course_id)

    assert result.grade_items[0].max_grade == 100


def test_finalgrade_is_extracted(moodle_engine: Engine) -> None:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        item_id = insert_grade_item(connection, courseid=course_id)
        insert_grade_grade(connection, itemid=item_id, userid=3, finalgrade=30)

    result = extract_moodle_grades_batch(moodle_engine, course_id)

    assert len(result.student_grades) == 1
    assert result.student_grades[0].finalgrade == 30
    assert result.student_grades[0].student_source_id == "3"


def test_null_finalgrade_stays_none(moodle_engine: Engine) -> None:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        item_id = insert_grade_item(connection, courseid=course_id)
        insert_grade_grade(connection, itemid=item_id, userid=3, finalgrade=None)

    result = extract_moodle_grades_batch(moodle_engine, course_id)

    assert result.student_grades[0].finalgrade is None


def test_zero_finalgrade_stays_zero_not_none(moodle_engine: Engine) -> None:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        item_id = insert_grade_item(connection, courseid=course_id)
        insert_grade_grade(connection, itemid=item_id, userid=3, finalgrade=0)

    result = extract_moodle_grades_batch(moodle_engine, course_id)

    assert result.student_grades[0].finalgrade == 0
    assert result.student_grades[0].finalgrade is not None


def test_hidden_flag_is_extracted_not_dropped(moodle_engine: Engine) -> None:
    """Extraction never filters hidden rows — that happens later, in
    staging (see grades_staging_writer.py). The extraction layer's job is
    to observe Moodle faithfully.
    """
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        item_id = insert_grade_item(connection, courseid=course_id, hidden=1)
        insert_grade_grade(connection, itemid=item_id, userid=3, finalgrade=30, hidden=1)

    result = extract_moodle_grades_batch(moodle_engine, course_id)

    assert result.grade_items[0].hidden is True
    assert result.student_grades[0].hidden is True


def test_course_scope_is_enforced(moodle_engine: Engine) -> None:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        other_course_id = insert_course(connection, fullname="Algebra I")
        insert_grade_item(connection, courseid=course_id, itemname="In scope")
        insert_grade_item(connection, courseid=other_course_id, itemname="Out of scope")

    result = extract_moodle_grades_batch(moodle_engine, course_id)

    assert len(result.grade_items) == 1
    assert result.grade_items[0].name == "In scope"


def test_grade_is_scoped_through_its_items_course(moodle_engine: Engine) -> None:
    """A grade joined to an item outside the configured course must never
    be extracted, even if its own row has no course reference of its own.
    """
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        other_course_id = insert_course(connection, fullname="Algebra I")
        in_scope_item = insert_grade_item(connection, courseid=course_id)
        out_of_scope_item = insert_grade_item(connection, courseid=other_course_id)
        insert_grade_grade(connection, itemid=in_scope_item, userid=3, finalgrade=30)
        insert_grade_grade(connection, itemid=out_of_scope_item, userid=4, finalgrade=75)

    result = extract_moodle_grades_batch(moodle_engine, course_id)

    assert len(result.student_grades) == 1
    assert result.student_grades[0].student_source_id == "3"
