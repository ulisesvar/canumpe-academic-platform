"""Builds staging.grade_items/student_grades from one batch's extracted
grade rows.

Staging is fully rebuilt for this source_system on every run. Only
structurally well-formed, *visible* rows are written; anything else is
either reported as a blocking issue (missing required field) or, for
hidden rows, silently excluded — see the README's hidden-data section
for why hidden is not treated as a data-quality problem. A student grade
is excluded whenever it is itself marked hidden, or whenever its parent
grade item is hidden (Moodle's own semantics: a hidden item hides every
grade under it regardless of any per-grade override), so a hidden
activity's grades can never leak into staging even if an individual
grade row's own hidden flag says otherwise.
"""

import uuid

from sqlalchemy import delete, insert
from sqlalchemy.engine import Connection

from app.integration.moodle.grades_hashing import grade_item_hash, student_grade_hash
from app.integration.moodle.grades_source import MoodleGradesExtractionResult
from app.integration.moodle.models.grades_staging import StagingGradeItem, StagingStudentGrade

SOURCE_SYSTEM = "moodle"


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def write_staging_grades_batch(
    connection: Connection,
    batch_id: uuid.UUID,
    moodle_course_id: int,
    extraction: MoodleGradesExtractionResult,
) -> list[str]:
    issues: list[str] = []
    course_source_id = str(moodle_course_id)

    connection.execute(
        delete(StagingGradeItem).where(StagingGradeItem.source_system == SOURCE_SYSTEM)
    )
    connection.execute(
        delete(StagingStudentGrade).where(StagingStudentGrade.source_system == SOURCE_SYSTEM)
    )

    hidden_item_source_ids: set[str] = set()
    item_rows = []
    for item in extraction.grade_items:
        if item.hidden:
            hidden_item_source_ids.add(item.source_id)
            continue

        name = _clean_text(item.name)
        if not name:
            issues.append(f"grade item source_id={item.source_id!r} is missing name")
            continue
        if item.max_grade is None or item.max_grade <= 0:
            issues.append(
                f"grade item source_id={item.source_id!r} has an invalid "
                f"max_grade {item.max_grade!r}"
            )
            continue

        item_rows.append(
            {
                "batch_id": batch_id,
                "source_system": SOURCE_SYSTEM,
                "source_id": item.source_id,
                "course_source_id": course_source_id,
                "name": name,
                "itemmodule": _clean_text(item.itemmodule),
                "max_grade": item.max_grade,
                "source_hash": grade_item_hash(
                    course_source_id, item.name, item.itemmodule, item.max_grade, item.hidden
                ),
            }
        )
    if item_rows:
        connection.execute(insert(StagingGradeItem), item_rows)

    grade_rows = []
    for g in extraction.student_grades:
        if g.hidden or g.grade_item_source_id in hidden_item_source_ids:
            continue

        student_source_id = _clean_text(g.student_source_id)
        if not student_source_id:
            issues.append(f"student grade source_id={g.source_id!r} is missing student_source_id")
            continue

        grade_rows.append(
            {
                "batch_id": batch_id,
                "source_system": SOURCE_SYSTEM,
                "source_id": g.source_id,
                "grade_item_source_id": g.grade_item_source_id,
                "student_source_id": student_source_id,
                "grade": g.finalgrade,
                "source_hash": student_grade_hash(
                    g.grade_item_source_id, g.student_source_id, g.finalgrade, g.hidden
                ),
            }
        )
    if grade_rows:
        connection.execute(insert(StagingStudentGrade), grade_rows)

    return issues
