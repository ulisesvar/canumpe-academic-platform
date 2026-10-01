"""Moodle activity type -> evaluation category assignment during the grades
sync — see app.integration.moodle.grades_merge
._sync_grade_item_evaluations_by_activity_type.

The category a grade item lands in is decided only by
GradeCategory.moodle_activity_type matching GradeItem.activity_type (the
Moodle itemmodule) — never by a category's name or id. The sync only ever
creates MISSING grade_item_evaluation rows; it never changes an existing one.
"""

from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, insert, select, text

from app.academic.models import Course, GradeCategory, GradeItem, GradeItemEvaluation
from app.integration.moodle import grades_merge
from app.integration.moodle.grades_sync import run_moodle_grades_sync
from tests.integration.moodle.fake_moodle import insert_course, insert_grade_item
from tests.integration.moodle.grades_helpers import seed_moodle_course_mapping

ASSIGNMENTS = "Entregables / tareas"
PARTICIPATION = "Participación / asistencia"
EXAMS = "Exámenes"


def _moodle_course(
    moodle_engine: Engine, app_engine: Engine, items: dict[str, str]
) -> tuple[int, int]:
    """A Moodle course with one visible grade item per (name -> itemmodule),
    mapped to a canonical course. Returns (moodle_course_id, academic_course_id).
    """
    with moodle_engine.begin() as connection:
        moodle_course_id = insert_course(connection, fullname="APS 2027-1")
        for name, itemmodule in items.items():
            insert_grade_item(
                connection, courseid=moodle_course_id, itemname=name, itemmodule=itemmodule
            )
    return moodle_course_id, seed_moodle_course_mapping(app_engine, moodle_course_id)


def _category(
    app_engine: Engine,
    course_id: int,
    name: str,
    weight: str,
    sort_order: int,
    *,
    moodle_activity_type: str | None = None,
    calculation_type: str = "GRADE_ITEMS",
) -> int:
    with app_engine.begin() as connection:
        return connection.execute(
            insert(GradeCategory)
            .values(
                course_id=course_id,
                name=name,
                weight_percent=Decimal(weight),
                sort_order=sort_order,
                moodle_activity_type=moodle_activity_type,
                calculation_type=calculation_type,
            )
            .returning(GradeCategory.id)
        ).scalar_one()


def _assignments(app_engine: Engine) -> dict[str, tuple[int, bool]]:
    """grade item name -> (category_id, counts_toward_current_grade), for
    items that have an assignment."""
    with app_engine.connect() as connection:
        rows = connection.execute(
            select(
                GradeItem.name,
                GradeItemEvaluation.category_id,
                GradeItemEvaluation.counts_toward_current_grade,
            ).join(GradeItemEvaluation, GradeItemEvaluation.grade_item_id == GradeItem.id)
        ).all()
    return {r.name: (r.category_id, r.counts_toward_current_grade) for r in rows}


def _unassigned(app_engine: Engine) -> set[str]:
    with app_engine.connect() as connection:
        return set(
            connection.execute(
                select(GradeItem.name)
                .outerjoin(GradeItemEvaluation, GradeItemEvaluation.grade_item_id == GradeItem.id)
                .where(GradeItemEvaluation.grade_item_id.is_(None))
            ).scalars()
        )


def _evaluation_count(app_engine: Engine) -> int:
    with app_engine.connect() as connection:
        return connection.execute(
            select(func.count()).select_from(GradeItemEvaluation)
        ).scalar_one()


def _sync(app_engine: Engine, moodle_engine: Engine, moodle_course_id: int) -> None:
    outcome = run_moodle_grades_sync(app_engine, moodle_engine, moodle_course_id)
    assert outcome.status == "SUCCESS", outcome.issues


# -- the assignment rule -------------------------------------------------


def test_assign_item_is_assigned_to_the_assign_category(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    moodle_course_id, course_id = _moodle_course(moodle_engine, app_engine, {"Tarea 01": "assign"})
    assign_category = _category(
        app_engine, course_id, ASSIGNMENTS, "100", 1, moodle_activity_type="assign"
    )

    _sync(app_engine, moodle_engine, moodle_course_id)

    assert _assignments(app_engine) == {"Tarea 01": (assign_category, True)}


def test_quiz_item_is_assigned_to_the_quiz_category(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    moodle_course_id, course_id = _moodle_course(moodle_engine, app_engine, {"Examen 1": "quiz"})
    _category(app_engine, course_id, ASSIGNMENTS, "40", 1, moodle_activity_type="assign")
    quiz_category = _category(app_engine, course_id, EXAMS, "60", 2, moodle_activity_type="quiz")

    _sync(app_engine, moodle_engine, moodle_course_id)

    assert _assignments(app_engine) == {"Examen 1": (quiz_category, True)}


def test_an_activity_type_with_no_configured_category_stays_unassigned(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    moodle_course_id, course_id = _moodle_course(
        moodle_engine, app_engine, {"Tarea 01": "assign", "Foro 1": "forum"}
    )
    assign_category = _category(
        app_engine, course_id, ASSIGNMENTS, "100", 1, moodle_activity_type="assign"
    )

    _sync(app_engine, moodle_engine, moodle_course_id)

    assert _assignments(app_engine) == {"Tarea 01": (assign_category, True)}
    assert _unassigned(app_engine) == {"Foro 1"}


def test_an_item_with_no_activity_type_is_never_assigned(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    with moodle_engine.begin() as connection:
        moodle_course_id = insert_course(connection, fullname="C")
        insert_grade_item(
            connection, courseid=moodle_course_id, itemname="Sin tipo", itemmodule=None
        )
    course_id = seed_moodle_course_mapping(app_engine, moodle_course_id)
    _category(app_engine, course_id, ASSIGNMENTS, "100", 1, moodle_activity_type="assign")

    _sync(app_engine, moodle_engine, moodle_course_id)

    assert _assignments(app_engine) == {}
    assert _unassigned(app_engine) == {"Sin tipo"}


def test_the_category_is_matched_by_activity_type_not_by_name_or_id(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    """Names are configurable and ids are per-database: swapping names and
    declaration order must not change where items go."""
    moodle_course_id, course_id = _moodle_course(
        moodle_engine, app_engine, {"Tarea 01": "assign", "Examen 1": "quiz"}
    )
    # Created in the "wrong" order, with names that suggest the opposite.
    quiz_category = _category(app_engine, course_id, "Tareas", "50", 1, moodle_activity_type="quiz")
    assign_category = _category(
        app_engine, course_id, "Exámenes", "50", 2, moodle_activity_type="assign"
    )

    _sync(app_engine, moodle_engine, moodle_course_id)

    assert _assignments(app_engine) == {
        "Tarea 01": (assign_category, True),
        "Examen 1": (quiz_category, True),
    }


def test_a_participation_category_never_receives_moodle_items(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    """Defensive: even if an ATTENDANCE_PARTICIPATION row somehow carried a
    moodle_activity_type (the scheme API rejects it), items aren't assigned to it."""
    moodle_course_id, course_id = _moodle_course(moodle_engine, app_engine, {"Tarea 01": "assign"})
    _category(
        app_engine,
        course_id,
        PARTICIPATION,
        "20",
        1,
        moodle_activity_type="assign",
        calculation_type="ATTENDANCE_PARTICIPATION",
    )

    _sync(app_engine, moodle_engine, moodle_course_id)

    assert _assignments(app_engine) == {}


# -- existing assignments are never overwritten ---------------------------


def test_existing_assignments_are_preserved_across_a_sync(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    moodle_course_id, course_id = _moodle_course(
        moodle_engine, app_engine, {"Tarea 01": "assign", "Tarea 02": "assign"}
    )
    _sync(app_engine, moodle_engine, moodle_course_id)  # items exist, nothing configured yet
    assign_category = _category(
        app_engine, course_id, ASSIGNMENTS, "50", 1, moodle_activity_type="assign"
    )
    other_category = _category(app_engine, course_id, "Proyecto", "50", 2)
    with app_engine.begin() as connection:
        tarea_01 = connection.execute(
            select(GradeItem.id).where(GradeItem.name == "Tarea 01")
        ).scalar_one()
        connection.execute(
            insert(GradeItemEvaluation).values(
                grade_item_id=tarea_01,
                category_id=other_category,
                counts_toward_current_grade=False,
            )
        )

    _sync(app_engine, moodle_engine, moodle_course_id)

    assignments = _assignments(app_engine)
    # Tarea 01 keeps its academic configuration: a different category, not counted.
    assert assignments["Tarea 01"] == (other_category, False)
    # Tarea 02 had none, so it is assigned automatically and counts.
    assert assignments["Tarea 02"] == (assign_category, True)


def test_a_second_sync_is_idempotent(app_engine: Engine, moodle_engine: Engine) -> None:
    moodle_course_id, course_id = _moodle_course(
        moodle_engine, app_engine, {"Tarea 01": "assign", "Tarea 02": "assign", "Examen 1": "quiz"}
    )
    _category(app_engine, course_id, ASSIGNMENTS, "40", 1, moodle_activity_type="assign")
    _category(app_engine, course_id, EXAMS, "60", 2, moodle_activity_type="quiz")

    _sync(app_engine, moodle_engine, moodle_course_id)
    first = _assignments(app_engine)
    first_count = _evaluation_count(app_engine)
    _sync(app_engine, moodle_engine, moodle_course_id)
    _sync(app_engine, moodle_engine, moodle_course_id)

    assert first_count == 3
    assert _evaluation_count(app_engine) == 3  # no duplicates
    assert _assignments(app_engine) == first  # nothing changed


def test_an_unassigned_item_is_assigned_once_a_category_for_its_type_is_configured(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    moodle_course_id, course_id = _moodle_course(moodle_engine, app_engine, {"Foro 1": "forum"})
    _sync(app_engine, moodle_engine, moodle_course_id)
    assert _unassigned(app_engine) == {"Foro 1"}

    forum_category = _category(
        app_engine, course_id, "Foros", "100", 1, moodle_activity_type="forum"
    )
    _sync(app_engine, moodle_engine, moodle_course_id)

    assert _assignments(app_engine) == {"Foro 1": (forum_category, True)}


# -- scope: only the current batch's items --------------------------------


def test_only_the_current_batchs_items_are_considered(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    moodle_course_id, course_id = _moodle_course(moodle_engine, app_engine, {"Tarea 01": "assign"})
    assign_category = _category(
        app_engine, course_id, ASSIGNMENTS, "100", 1, moodle_activity_type="assign"
    )
    with app_engine.begin() as connection:
        # A canonical item of the same course that is NOT in this sync's batch.
        connection.execute(
            insert(GradeItem).values(
                course_id=course_id, name="Fuera del batch", max_grade=100, activity_type="assign"
            )
        )
        # Another course with its own mapped category and an unassigned item.
        other_course = connection.execute(
            insert(Course).values(name="Otro curso").returning(Course.id)
        ).scalar_one()
        connection.execute(
            insert(GradeCategory).values(
                course_id=other_course,
                name="Tareas",
                weight_percent=100,
                sort_order=1,
                moodle_activity_type="assign",
            )
        )
        connection.execute(
            insert(GradeItem).values(
                course_id=other_course,
                name="Otro curso: tarea",
                max_grade=100,
                activity_type="assign",
            )
        )

    _sync(app_engine, moodle_engine, moodle_course_id)

    assert _assignments(app_engine) == {"Tarea 01": (assign_category, True)}
    assert _unassigned(app_engine) == {"Fuera del batch", "Otro curso: tarea"}


# -- atomicity ------------------------------------------------------------


def test_the_assignment_is_part_of_the_merge_transaction(
    app_engine: Engine, moodle_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    moodle_course_id, course_id = _moodle_course(moodle_engine, app_engine, {"Tarea 01": "assign"})
    _category(app_engine, course_id, ASSIGNMENTS, "100", 1, moodle_activity_type="assign")

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("merge failed after the items were merged")

    monkeypatch.setattr(grades_merge, "_merge_student_grades", _boom)

    outcome = run_moodle_grades_sync(app_engine, moodle_engine, moodle_course_id)

    assert outcome.status == "FAILED"
    with app_engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(GradeItem)).scalar_one() == 0
    assert _evaluation_count(app_engine) == 0


# -- regression: activity_type still comes from itemmodule ----------------


@pytest.mark.parametrize("itemmodule", ["assign", "quiz", "forum"])
def test_activity_type_is_still_stored_from_itemmodule(
    app_engine: Engine, moodle_engine: Engine, itemmodule: str
) -> None:
    moodle_course_id, _ = _moodle_course(moodle_engine, app_engine, {"Actividad": itemmodule})

    _sync(app_engine, moodle_engine, moodle_course_id)

    with app_engine.connect() as connection:
        activity_type = connection.execute(select(GradeItem.activity_type)).scalar_one()
    assert activity_type == itemmodule


def test_activity_type_follows_a_changed_itemmodule(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    moodle_course_id, _ = _moodle_course(moodle_engine, app_engine, {"Actividad": "assign"})
    _sync(app_engine, moodle_engine, moodle_course_id)

    with moodle_engine.begin() as connection:
        connection.execute(text("UPDATE mdl_grade_items SET itemmodule = 'quiz'"))
    _sync(app_engine, moodle_engine, moodle_course_id)

    with app_engine.connect() as connection:
        assert connection.execute(select(GradeItem.activity_type)).scalar_one() == "quiz"


# -- the real production case ---------------------------------------------


def test_production_course_assigns_all_four_activities_to_the_right_categories(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    """Tarea 01/02/03 (assign) and Examen 1 (quiz), with the course's three
    categories — assignments (assign), participation/attendance (no Moodle
    type) and exams (quiz). None of the four may be left unassigned."""
    moodle_course_id, course_id = _moodle_course(
        moodle_engine,
        app_engine,
        {
            "Tarea 01": "assign",
            "Tarea 02": "assign",
            "Tarea 03": "assign",
            "Examen 1 Administración de la Configuración, Métricas y Riesgos": "quiz",
        },
    )
    assignments_category = _category(
        app_engine, course_id, ASSIGNMENTS, "40", 1, moodle_activity_type="assign"
    )
    participation_category = _category(
        app_engine, course_id, PARTICIPATION, "20", 2, calculation_type="ATTENDANCE_PARTICIPATION"
    )
    exams_category = _category(app_engine, course_id, EXAMS, "40", 3, moodle_activity_type="quiz")

    _sync(app_engine, moodle_engine, moodle_course_id)
    _sync(app_engine, moodle_engine, moodle_course_id)  # and again: still the same

    assert _assignments(app_engine) == {
        "Tarea 01": (assignments_category, True),
        "Tarea 02": (assignments_category, True),
        "Tarea 03": (assignments_category, True),
        "Examen 1 Administración de la Configuración, Métricas y Riesgos": (exams_category, True),
    }
    assert _unassigned(app_engine) == set()
    assert participation_category not in {
        category for category, _ in _assignments(app_engine).values()
    }
