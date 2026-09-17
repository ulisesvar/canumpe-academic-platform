"""Read-only extraction of Moodle grade items/grades for one course.

Queries only, no writes — same security boundary as
app.integration.moodle.source. Both queries run inside one REPEATABLE
READ, READ ONLY transaction so grade items and the grades that reference
them represent one coherent snapshot.

Only itemtype='mod' grade items are ever selected — the course total
(itemtype='course', itemname NULL) and any category totals are excluded
by the query itself, not by later filtering, so they never reach RAW at
all. Grades are joined back through mdl_grade_items scoped the same way,
so a grade can never be extracted for an item outside the configured
course or outside itemtype='mod' — see the README's grade-item filter
section.

Only the columns academic grading actually needs are selected — never
rawgrade/rawgrademin/rawgrademax/feedback/information/overridden/
excluded/aggregation weights/outcomes/scales/grade history/letters. See
the README's minimal-data principle.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

#: Moodle grade_items rows this pipeline canonicalizes. 'course' (the
#: course total) and any category aggregate rows are never selected.
MOD_ITEM_TYPE = "mod"


def _epoch_to_datetime(value: int | None) -> datetime | None:
    """Moodle stores modification times as unix epoch seconds; 0/None means unset."""
    if not value:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


@dataclass(frozen=True)
class ExtractedGradeItem:
    source_id: str
    name: str | None
    itemmodule: str | None
    max_grade: Decimal | None
    hidden: bool
    source_updated_at: datetime | None


@dataclass(frozen=True)
class ExtractedStudentGrade:
    source_id: str
    grade_item_source_id: str
    student_source_id: str | None
    finalgrade: Decimal | None
    hidden: bool
    source_updated_at: datetime | None


@dataclass(frozen=True)
class MoodleGradesExtractionResult:
    snapshot_time: datetime
    grade_items: Sequence[ExtractedGradeItem]
    student_grades: Sequence[ExtractedStudentGrade]


def _fetch_grade_items(connection: Connection, course_id: int) -> list[ExtractedGradeItem]:
    rows = connection.execute(
        text("""
            SELECT id AS source_id, itemname, itemmodule, grademax, hidden, timemodified
            FROM mdl_grade_items
            WHERE courseid = :course_id AND itemtype = :item_type
        """),
        {"course_id": course_id, "item_type": MOD_ITEM_TYPE},
    ).all()
    return [
        ExtractedGradeItem(
            source_id=str(row.source_id),
            name=row.itemname,
            itemmodule=row.itemmodule,
            max_grade=row.grademax,
            hidden=bool(row.hidden),
            source_updated_at=_epoch_to_datetime(row.timemodified),
        )
        for row in rows
    ]


def _fetch_student_grades(connection: Connection, course_id: int) -> list[ExtractedStudentGrade]:
    rows = connection.execute(
        text("""
            SELECT
                gg.id AS source_id,
                gg.itemid AS grade_item_source_id,
                gg.userid AS student_source_id,
                gg.finalgrade,
                gg.hidden,
                gg.timemodified
            FROM mdl_grade_grades gg
            JOIN mdl_grade_items gi ON gi.id = gg.itemid
            WHERE gi.courseid = :course_id AND gi.itemtype = :item_type
        """),
        {"course_id": course_id, "item_type": MOD_ITEM_TYPE},
    ).all()
    return [
        ExtractedStudentGrade(
            source_id=str(row.source_id),
            grade_item_source_id=str(row.grade_item_source_id),
            student_source_id=str(row.student_source_id)
            if row.student_source_id is not None
            else None,
            finalgrade=row.finalgrade,
            hidden=bool(row.hidden),
            source_updated_at=_epoch_to_datetime(row.timemodified),
        )
        for row in rows
    ]


def extract_moodle_grades_batch(
    moodle_engine: Engine, course_id: int
) -> MoodleGradesExtractionResult:
    """Extract grade items/grades for one course from Moodle.

    Runs inside a single REPEATABLE READ, READ ONLY transaction — same
    pattern as app.integration.moodle.source.extract_moodle_batch — so
    both queries see one consistent snapshot of Moodle's gradebook. The
    transaction is always committed (read-only, so this just releases
    the snapshot) or rolled back on error, and the connection is always
    closed.
    """
    with moodle_engine.connect() as connection, connection.begin():
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        snapshot_time = connection.execute(text("SELECT now()")).scalar_one()

        grade_items = _fetch_grade_items(connection, course_id)
        student_grades = _fetch_student_grades(connection, course_id)

    return MoodleGradesExtractionResult(
        snapshot_time=snapshot_time, grade_items=grade_items, student_grades=student_grades
    )
