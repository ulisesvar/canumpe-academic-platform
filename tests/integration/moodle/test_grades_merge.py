from sqlalchemy import Engine, select, text

from app.academic.models import GradeItem, StudentGrade
from app.integration.models import GradeItemSource, StudentGradeSource
from app.integration.moodle.grades_sync import run_moodle_grades_sync
from tests.integration.moodle.fake_moodle import (
    insert_course,
    insert_grade_grade,
    insert_grade_item,
    update_grade_grade_finalgrade,
    update_grade_item_name,
)
from tests.integration.moodle.grades_helpers import (
    seed_moodle_course_mapping,
    seed_moodle_student_mapping,
)

MOODLE_USER_ID = 3


def _seed(moodle_engine: Engine, app_engine: Engine) -> tuple[int, int, int, int]:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        item_id = insert_grade_item(connection, courseid=course_id, itemname="Tarea 01")
        insert_grade_grade(connection, itemid=item_id, userid=MOODLE_USER_ID, finalgrade=30)
    academic_course_id = seed_moodle_course_mapping(app_engine, course_id)
    academic_student_id = seed_moodle_student_mapping(app_engine, MOODLE_USER_ID)
    return course_id, academic_course_id, item_id, academic_student_id


def test_first_sync_inserts_grade_item(app_engine: Engine, moodle_engine: Engine) -> None:
    course_id, academic_course_id, _, _ = _seed(moodle_engine, app_engine)

    outcome = run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    assert outcome.status == "SUCCESS"
    with app_engine.begin() as connection:
        items = connection.execute(select(GradeItem)).all()
    assert len(items) == 1
    assert items[0].name == "Tarea 01"
    assert items[0].course_id == academic_course_id
    assert items[0].max_grade == 100


def test_first_sync_inserts_student_grade(app_engine: Engine, moodle_engine: Engine) -> None:
    course_id, _, _, academic_student_id = _seed(moodle_engine, app_engine)

    run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        grades = connection.execute(select(StudentGrade)).all()
    assert len(grades) == 1
    assert grades[0].student_id == academic_student_id
    assert grades[0].grade == 30


def test_grade_item_mapping_created(app_engine: Engine, moodle_engine: Engine) -> None:
    course_id, _, item_id, _ = _seed(moodle_engine, app_engine)

    run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        mapping = connection.execute(
            select(GradeItemSource).where(
                GradeItemSource.source_system == "moodle",
                GradeItemSource.source_id == str(item_id),
            )
        ).one()
    assert mapping.grade_item_id is not None


def test_student_grade_mapping_created(app_engine: Engine, moodle_engine: Engine) -> None:
    course_id, _, _, _ = _seed(moodle_engine, app_engine)

    run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        mapping = connection.execute(select(StudentGradeSource)).one()
    assert mapping.source_system == "moodle"


def test_moodle_student_mapping_resolves_canonical_student(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, _, _, academic_student_id = _seed(moodle_engine, app_engine)

    run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        grade = connection.execute(select(StudentGrade)).one()
    assert grade.student_id == academic_student_id


def test_moodle_course_mapping_resolves_canonical_course(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, academic_course_id, _, _ = _seed(moodle_engine, app_engine)

    run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        item = connection.execute(select(GradeItem)).one()
    assert item.course_id == academic_course_id


def test_identical_second_sync_creates_no_duplicates(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, _, _, _ = _seed(moodle_engine, app_engine)

    run_moodle_grades_sync(app_engine, moodle_engine, course_id)
    run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        assert len(connection.execute(select(GradeItem)).all()) == 1
        assert len(connection.execute(select(StudentGrade)).all()) == 1
        assert len(connection.execute(select(GradeItemSource)).all()) == 1
        assert len(connection.execute(select(StudentGradeSource)).all()) == 1


def test_identical_second_sync_reports_unchanged(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, _, _, _ = _seed(moodle_engine, app_engine)

    run_moodle_grades_sync(app_engine, moodle_engine, course_id)
    second = run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    assert second.status == "SUCCESS"
    assert second.merge_result is not None
    assert second.merge_result.counters.rows_inserted == 0
    assert second.merge_result.counters.rows_updated == 0
    assert second.merge_result.counters.rows_unchanged == 2  # grade item + student grade


def test_grade_change_updates_the_same_canonical_student_grade_row(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, _, _, _ = _seed(moodle_engine, app_engine)
    run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        original_id = connection.execute(select(StudentGrade.id)).scalar_one()

    with moodle_engine.begin() as connection:
        gradeid = connection.execute(text("SELECT id FROM mdl_grade_grades")).scalar_one()
        update_grade_grade_finalgrade(connection, gradeid, 80)

    outcome = run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        grade = connection.execute(select(StudentGrade)).one()

    assert outcome.merge_result is not None
    assert outcome.merge_result.counters.rows_updated == 1
    assert grade.id == original_id
    assert grade.grade == 80


def test_grade_item_name_change_updates_the_same_canonical_item(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, _, item_id, _ = _seed(moodle_engine, app_engine)
    run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        original_id = connection.execute(select(GradeItem.id)).scalar_one()

    with moodle_engine.begin() as connection:
        update_grade_item_name(connection, item_id, "Tarea 01 (revisada)")

    outcome = run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        item = connection.execute(select(GradeItem)).one()

    assert outcome.merge_result is not None
    assert outcome.merge_result.counters.rows_updated == 1
    assert item.id == original_id
    assert item.name == "Tarea 01 (revisada)"


def test_null_finalgrade_remains_null_in_canonical(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        item_id = insert_grade_item(connection, courseid=course_id, itemname="Tarea 01")
        insert_grade_grade(connection, itemid=item_id, userid=MOODLE_USER_ID, finalgrade=None)
    seed_moodle_course_mapping(app_engine, course_id)
    seed_moodle_student_mapping(app_engine, MOODLE_USER_ID)

    outcome = run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    assert outcome.status == "SUCCESS"
    with app_engine.begin() as connection:
        grade = connection.execute(select(StudentGrade)).one()
    assert grade.grade is None


def test_zero_finalgrade_remains_numeric_zero_in_canonical(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        item_id = insert_grade_item(connection, courseid=course_id, itemname="Tarea 01")
        insert_grade_grade(connection, itemid=item_id, userid=MOODLE_USER_ID, finalgrade=0)
    seed_moodle_course_mapping(app_engine, course_id)
    seed_moodle_student_mapping(app_engine, MOODLE_USER_ID)

    outcome = run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    assert outcome.status == "SUCCESS"
    with app_engine.begin() as connection:
        grade = connection.execute(select(StudentGrade)).one()
    assert grade.grade == 0
    assert grade.grade is not None
