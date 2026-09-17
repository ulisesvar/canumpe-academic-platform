"""Batch-level data-quality checks over already-staged grade rows.

Row-level checks (missing required fields, hidden exclusion) happen
while staging is being built — see grades_staging_writer.py. This module
checks properties that require seeing the whole batch at once, plus
course resolution through the existing Moodle course mapping. A blocking
issue here must abort the entire batch.

Unlike Attendance's account_number reconciliation, a Moodle student
grade's student_source_id resolving to *zero* matches in
integration.student_sources is deliberately NOT checked here — it is a
per-row, non-blocking skip handled by grades_merge.py (see
UNRESOLVED_GRADE_STUDENT), exactly analogous to Attendance's unresolved-
student skip. A grade's student_source_id can never resolve to *more*
than one match (integration.student_sources has
UNIQUE(source_system, source_id)), so there is no ambiguous case to
guard against here.
"""

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from app.integration.models import CourseSource
from app.integration.moodle.models.grades_staging import StagingGradeItem, StagingStudentGrade

MOODLE_SOURCE_SYSTEM = "moodle"


def resolve_moodle_course_id(connection: Connection, moodle_course_id: int) -> int | None:
    """Looks up the canonical academic.courses.id for the configured
    Moodle course, through the existing Moodle course source mapping.
    Never a hardcoded academic.courses.id.
    """
    return connection.execute(
        select(CourseSource.course_id).where(
            CourseSource.source_system == MOODLE_SOURCE_SYSTEM,
            CourseSource.source_id == str(moodle_course_id),
        )
    ).scalar_one_or_none()


def validate_staged_grades_batch(connection: Connection, moodle_course_id: int) -> list[str]:
    issues: list[str] = []

    if resolve_moodle_course_id(connection, moodle_course_id) is None:
        issues.append(
            f"no integration.course_sources mapping for moodle course_id={moodle_course_id!r} "
            "— grades cannot be associated with a course"
        )

    grade_item_source_ids = set(
        connection.execute(
            select(StagingGradeItem.source_id).where(
                StagingGradeItem.source_system == MOODLE_SOURCE_SYSTEM
            )
        ).scalars()
    )

    grades = connection.execute(
        select(
            StagingStudentGrade.source_id,
            StagingStudentGrade.grade_item_source_id,
            StagingStudentGrade.student_source_id,
        ).where(StagingStudentGrade.source_system == MOODLE_SOURCE_SYSTEM)
    ).all()
    for source_id, grade_item_source_id, _student_source_id in grades:
        if grade_item_source_id not in grade_item_source_ids:
            issues.append(
                f"student grade source_id={source_id!r} references unknown "
                f"grade_item_source_id={grade_item_source_id!r}"
            )

    duplicate_pairs = connection.execute(
        select(
            StagingStudentGrade.grade_item_source_id,
            StagingStudentGrade.student_source_id,
            func.count().label("n"),
        )
        .where(StagingStudentGrade.source_system == MOODLE_SOURCE_SYSTEM)
        .group_by(
            StagingStudentGrade.grade_item_source_id, StagingStudentGrade.student_source_id
        )
        .having(func.count() > 1)
    ).all()
    for grade_item_source_id, student_source_id, count in duplicate_pairs:
        issues.append(
            f"duplicate grade for grade_item_source_id={grade_item_source_id!r} "
            f"student_source_id={student_source_id!r} ({count} source rows)"
        )

    return issues
