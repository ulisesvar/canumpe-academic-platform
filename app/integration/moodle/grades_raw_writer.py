"""Writes one batch's extracted grade rows into raw_moodle.* — a
faithful, append-only landing copy. RAW is never validated and never
truncated by a sync run, and it keeps every row extraction observed —
including hidden ones — even though staging later excludes hidden rows
from ever becoming canonical.
"""

import uuid

from sqlalchemy import insert
from sqlalchemy.engine import Connection

from app.integration.moodle.grades_hashing import grade_item_hash, student_grade_hash
from app.integration.moodle.grades_source import MoodleGradesExtractionResult
from app.integration.moodle.models.grades_raw import RawMoodleGradeItem, RawMoodleStudentGrade


def write_raw_grades_batch(
    connection: Connection,
    batch_id: uuid.UUID,
    moodle_course_id: int,
    extraction: MoodleGradesExtractionResult,
) -> None:
    course_source_id = str(moodle_course_id)

    if extraction.grade_items:
        connection.execute(
            insert(RawMoodleGradeItem),
            [
                {
                    "batch_id": batch_id,
                    "source_id": item.source_id,
                    "course_source_id": course_source_id,
                    "name": item.name,
                    "itemmodule": item.itemmodule,
                    "max_grade": item.max_grade,
                    "hidden": item.hidden,
                    "source_updated_at": item.source_updated_at,
                    "source_hash": grade_item_hash(
                        course_source_id, item.name, item.itemmodule, item.max_grade, item.hidden
                    ),
                }
                for item in extraction.grade_items
            ],
        )

    if extraction.student_grades:
        connection.execute(
            insert(RawMoodleStudentGrade),
            [
                {
                    "batch_id": batch_id,
                    "source_id": g.source_id,
                    "grade_item_source_id": g.grade_item_source_id,
                    "student_source_id": g.student_source_id,
                    "grade": g.finalgrade,
                    "hidden": g.hidden,
                    "source_updated_at": g.source_updated_at,
                    "source_hash": student_grade_hash(
                        g.grade_item_source_id, g.student_source_id, g.finalgrade, g.hidden
                    ),
                }
                for g in extraction.student_grades
            ],
        )
