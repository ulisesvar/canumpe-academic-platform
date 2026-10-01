"""Migration 0011_category_moodle_activity: the new column and unique
constraint, the one-time backfill of today's categories, and a clean downgrade.
"""

from sqlalchemy import Engine, inspect, text

from alembic import command
from tests.conftest import alembic_config

PREVIOUS_REVISION = "0010_grade_category_calc_type"


def _columns(db_engine: Engine) -> set[str]:
    return {
        c["name"] for c in inspect(db_engine).get_columns("grade_categories", schema="academic")
    }


def _unique_names(db_engine: Engine) -> set[str]:
    constraints = inspect(db_engine).get_unique_constraints("grade_categories", schema="academic")
    return {c["name"] for c in constraints}


def test_upgrade_adds_a_nullable_column_and_the_per_course_unique_constraint(
    db_engine: Engine,
) -> None:
    columns = {
        c["name"]: c for c in inspect(db_engine).get_columns("grade_categories", schema="academic")
    }
    assert columns["moodle_activity_type"]["nullable"] is True
    assert "uq_grade_categories_course_moodle_activity_type" in _unique_names(db_engine)
    # The earlier constraints are still there.
    assert {
        "uq_grade_categories_course_name",
        "uq_grade_categories_course_sort_order",
    } <= _unique_names(db_engine)


def test_backfill_maps_todays_categories_and_nothing_else(db_engine: Engine) -> None:
    cfg = alembic_config()
    course_ids: list[int] = []

    try:
        command.downgrade(cfg, PREVIOUS_REVISION)
        assert "moodle_activity_type" not in _columns(db_engine)

        with db_engine.begin() as connection:
            for name in ("backfill-A", "backfill-B", "backfill-C"):
                course_ids.append(
                    connection.execute(
                        text("INSERT INTO academic.courses (name) VALUES (:n) RETURNING id"),
                        {"n": name},
                    ).scalar_one()
                )
            course_a, course_b, course_c = course_ids
            rows = [
                # (course, name, weight, sort_order, calculation_type)
                (course_a, "Entregables / tareas", 40, 1, "GRADE_ITEMS"),
                (course_a, "Participación / asistencia", 20, 2, "ATTENDANCE_PARTICIPATION"),
                (course_a, "Exámenes", 40, 3, "GRADE_ITEMS"),
                # case / surrounding spaces don't matter; unrelated names are untouched
                (course_b, "  EXÁMENES ", 50, 1, "GRADE_ITEMS"),
                (course_b, "Proyecto", 50, 2, "GRADE_ITEMS"),
                # an attendance/participation category is never mapped, whatever its name
                (course_c, "Exámenes", 100, 1, "ATTENDANCE_PARTICIPATION"),
            ]
            for course_id, name, weight, sort_order, calculation_type in rows:
                connection.execute(
                    text(
                        "INSERT INTO academic.grade_categories "
                        "(course_id, name, weight_percent, sort_order, calculation_type) "
                        "VALUES (:c, :n, :w, :s, :t)"
                    ),
                    {
                        "c": course_id,
                        "n": name,
                        "w": weight,
                        "s": sort_order,
                        "t": calculation_type,
                    },
                )

        command.upgrade(cfg, "head")

        with db_engine.connect() as connection:
            stored = {
                (r.course_id, r.name.strip()): r.moodle_activity_type
                for r in connection.execute(
                    text(
                        "SELECT course_id, name, moodle_activity_type "
                        "FROM academic.grade_categories WHERE course_id = ANY(:ids)"
                    ),
                    {"ids": course_ids},
                )
            }
        assert stored == {
            (course_a, "Entregables / tareas"): "assign",
            (course_a, "Participación / asistencia"): None,
            (course_a, "Exámenes"): "quiz",
            (course_b, "EXÁMENES"): "quiz",
            (course_b, "Proyecto"): None,
            (course_c, "Exámenes"): None,
        }
    finally:
        command.upgrade(cfg, "head")
        if course_ids:
            with db_engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM academic.grade_categories WHERE course_id = ANY(:ids)"),
                    {"ids": course_ids},
                )
                connection.execute(
                    text("DELETE FROM academic.courses WHERE id = ANY(:ids)"), {"ids": course_ids}
                )


def test_downgrade_one_step_removes_only_the_column_and_constraint(db_engine: Engine) -> None:
    cfg = alembic_config()

    try:
        command.downgrade(cfg, PREVIOUS_REVISION)
        assert "moodle_activity_type" not in _columns(db_engine)
        assert "uq_grade_categories_course_moodle_activity_type" not in _unique_names(db_engine)
        # 0010's column is untouched by downgrading 0011.
        assert "calculation_type" in _columns(db_engine)
    finally:
        command.upgrade(cfg, "head")

    assert "moodle_activity_type" in _columns(db_engine)
    assert "uq_grade_categories_course_moodle_activity_type" in _unique_names(db_engine)
