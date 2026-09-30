"""academic.grade_categories.calculation_type (migration
0010_grade_category_calc_type): default/backfill, CHECK, the one-per-
course partial unique index, and a clean downgrade.
"""

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.academic.models import Course, GradeCategory
from tests.conftest import alembic_config

PREVIOUS_REVISION = "0009_participation_observations"


def _course(db_session: Session, name: str = "Course") -> int:
    course = Course(name=name)
    db_session.add(course)
    db_session.commit()
    return course.id


def _column_names(db_engine: Engine) -> set[str]:
    return {
        c["name"] for c in inspect(db_engine).get_columns("grade_categories", schema="academic")
    }


def test_category_without_explicit_calculation_type_is_grade_items(db_session: Session) -> None:
    course_id = _course(db_session)
    db_session.add(
        GradeCategory(course_id=course_id, name="Tasks", weight_percent=100, sort_order=1)
    )
    db_session.commit()

    stored = db_session.query(GradeCategory.calculation_type).filter_by(course_id=course_id).one()
    assert stored.calculation_type == "GRADE_ITEMS"


def test_raw_insert_without_calculation_type_defaults_to_grade_items(db_session: Session) -> None:
    course_id = _course(db_session)

    stored = db_session.execute(
        text(
            "INSERT INTO academic.grade_categories (course_id, name, weight_percent, sort_order) "
            "VALUES (:course_id, 'Tasks', 100, 1) RETURNING calculation_type"
        ),
        {"course_id": course_id},
    ).scalar_one()

    assert stored == "GRADE_ITEMS"


def test_invalid_calculation_type_is_rejected_by_the_database(db_session: Session) -> None:
    course_id = _course(db_session)
    db_session.add(
        GradeCategory(
            course_id=course_id,
            name="Tasks",
            weight_percent=100,
            sort_order=1,
            calculation_type="BOGUS",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_a_course_can_have_only_one_attendance_participation_category(
    db_session: Session,
) -> None:
    course_id = _course(db_session)
    db_session.add(
        GradeCategory(
            course_id=course_id,
            name="A",
            weight_percent=10,
            sort_order=1,
            calculation_type="ATTENDANCE_PARTICIPATION",
        )
    )
    db_session.commit()

    db_session.add(
        GradeCategory(
            course_id=course_id,
            name="B",
            weight_percent=10,
            sort_order=2,
            calculation_type="ATTENDANCE_PARTICIPATION",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_the_one_per_course_rule_does_not_limit_other_categories_or_courses(
    db_session: Session,
) -> None:
    first = _course(db_session, "First")
    second = _course(db_session, "Second")
    for course_id in (first, second):
        db_session.add_all(
            [
                GradeCategory(course_id=course_id, name="T1", weight_percent=30, sort_order=1),
                GradeCategory(course_id=course_id, name="T2", weight_percent=30, sort_order=2),
                GradeCategory(
                    course_id=course_id,
                    name="A/P",
                    weight_percent=40,
                    sort_order=3,
                    calculation_type="ATTENDANCE_PARTICIPATION",
                ),
            ]
        )
    db_session.commit()

    assert (
        db_session.query(GradeCategory).filter(GradeCategory.course_id.in_([first, second])).count()
        == 6
    )


def test_migration_backfills_existing_categories_to_grade_items(db_engine: Engine) -> None:
    cfg = alembic_config()
    course_id: int | None = None

    try:
        command.downgrade(cfg, PREVIOUS_REVISION)
        assert "calculation_type" not in _column_names(db_engine)

        with db_engine.begin() as connection:
            course_id = connection.execute(
                text("INSERT INTO academic.courses (name) VALUES ('backfill-probe') RETURNING id")
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO academic.grade_categories "
                    "(course_id, name, weight_percent, sort_order) "
                    "VALUES (:c, 'Existing 1', 60, 1), (:c, 'Existing 2', 40, 2)"
                ),
                {"c": course_id},
            )

        command.upgrade(cfg, "head")

        with db_engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT name, weight_percent, sort_order, calculation_type "
                    "FROM academic.grade_categories WHERE course_id = :c ORDER BY sort_order"
                ),
                {"c": course_id},
            ).all()
        assert [(r.name, float(r.weight_percent), r.sort_order) for r in rows] == [
            ("Existing 1", 60.0, 1),
            ("Existing 2", 40.0, 2),
        ]
        assert [r.calculation_type for r in rows] == ["GRADE_ITEMS", "GRADE_ITEMS"]
    finally:
        command.upgrade(cfg, "head")
        if course_id is not None:
            with db_engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM academic.grade_categories WHERE course_id = :c"),
                    {"c": course_id},
                )
                connection.execute(
                    text("DELETE FROM academic.courses WHERE id = :c"), {"c": course_id}
                )


def test_downgrade_one_step_removes_only_the_calculation_type(db_engine: Engine) -> None:
    cfg = alembic_config()

    try:
        command.downgrade(cfg, PREVIOUS_REVISION)
        assert "calculation_type" not in _column_names(db_engine)
        assert {"id", "course_id", "name", "weight_percent", "sort_order"} <= _column_names(
            db_engine
        )
        # 0009 (participation observations) is untouched by downgrading 0010.
        assert "participation_observations" in inspect(db_engine).get_table_names(schema="academic")
        indexes = {
            i["name"] for i in inspect(db_engine).get_indexes("grade_categories", schema="academic")
        }
        assert "uq_grade_categories_course_attendance_participation" not in indexes
    finally:
        command.upgrade(cfg, "head")

    assert "calculation_type" in _column_names(db_engine)
    indexes = {
        i["name"] for i in inspect(db_engine).get_indexes("grade_categories", schema="academic")
    }
    assert "uq_grade_categories_course_attendance_participation" in indexes
