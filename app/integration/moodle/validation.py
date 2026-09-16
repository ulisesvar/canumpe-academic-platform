"""Batch-level data-quality checks over already-staged rows.

Row-level checks (missing required fields) happen while staging is being
built — see staging_writer.py. This module only checks properties that
require seeing the whole batch at once: duplicates and cross-entity
references. A blocking issue here must abort the entire batch; per the
architecture, we never merge "the good rows" and skip the rest.
"""

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from app.integration.moodle.models.staging import (
    StagingCourse,
    StagingEnrollment,
    StagingStudent,
)
from app.integration.moodle.staging_writer import SOURCE_SYSTEM


def validate_staged_batch(connection: Connection) -> list[str]:
    issues: list[str] = []

    duplicate_accounts = connection.execute(
        select(StagingStudent.account_number, func.count().label("n"))
        .where(StagingStudent.source_system == SOURCE_SYSTEM)
        .group_by(StagingStudent.account_number)
        .having(func.count() > 1)
    ).all()
    for account_number, count in duplicate_accounts:
        issues.append(
            f"duplicate account_number {account_number!r} appears in {count} source rows"
        )

    student_source_ids = set(
        connection.execute(
            select(StagingStudent.source_id).where(StagingStudent.source_system == SOURCE_SYSTEM)
        ).scalars()
    )
    course_source_ids = set(
        connection.execute(
            select(StagingCourse.source_id).where(StagingCourse.source_system == SOURCE_SYSTEM)
        ).scalars()
    )

    enrollments = connection.execute(
        select(
            StagingEnrollment.source_id,
            StagingEnrollment.student_source_id,
            StagingEnrollment.course_source_id,
        ).where(StagingEnrollment.source_system == SOURCE_SYSTEM)
    ).all()
    for source_id, student_source_id, course_source_id in enrollments:
        if student_source_id not in student_source_ids:
            issues.append(
                f"enrollment source_id={source_id!r} references unknown "
                f"student_source_id={student_source_id!r}"
            )
        if course_source_id not in course_source_ids:
            issues.append(
                f"enrollment source_id={source_id!r} references unknown "
                f"course_source_id={course_source_id!r}"
            )

    return issues
