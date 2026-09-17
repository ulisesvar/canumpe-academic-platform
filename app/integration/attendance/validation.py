"""Batch-level data-quality checks over already-staged Attendance rows.

Row-level checks (missing required fields) happen while staging is being
built — see staging_writer.py. This module checks properties that
require seeing the whole batch at once, plus two cross-database checks
that can only happen here: account_number reconciliation against
academic.students, and course resolution through the Moodle course
mapping. A blocking issue here must abort the entire batch.

One reconciliation outcome is deliberately NOT blocking: an
account_number that resolves to zero academic students (Moodle hasn't
created that student yet). That case is a per-student SKIP handled by
merge.py's _reconcile_students, not a batch failure — see
_reconciliation_issue below. Resolving to *more than one* academic
student remains blocking (structurally prevented by academic.students'
own UNIQUE(account_number), but checked here too, defensively).
"""

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from app.academic.models import Student
from app.integration.attendance.models.staging import (
    StagingAttendanceRecord,
    StagingAttendanceSession,
    StagingAttendanceStudent,
)
from app.integration.attendance.staging_writer import SOURCE_SYSTEM
from app.integration.models import CourseSource

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


def _reconciliation_issue(account_number: str, match_count: int) -> str | None:
    """The only account_number resolution outcome that blocks the batch:
    genuinely ambiguous (more than one academic student). Zero matches is
    not blocking — merge.py skips that student (and their attendance
    records) instead, since Moodle may simply not have created them yet;
    a later full sync picks them up automatically once it does.
    """
    if match_count > 1:
        return (
            f"attendance account_number {account_number!r} resolves ambiguously to "
            f"{match_count} academic students (expected exactly 1)"
        )
    return None


def validate_staged_batch(connection: Connection, moodle_course_id: int) -> list[str]:
    issues: list[str] = []

    if resolve_moodle_course_id(connection, moodle_course_id) is None:
        issues.append(
            f"no integration.course_sources mapping for moodle course_id={moodle_course_id!r} "
            "— Attendance cannot be associated with a course"
        )

    duplicate_accounts = connection.execute(
        select(StagingAttendanceStudent.account_number, func.count().label("n"))
        .where(StagingAttendanceStudent.source_system == SOURCE_SYSTEM)
        .group_by(StagingAttendanceStudent.account_number)
        .having(func.count() > 1)
    ).all()
    for account_number, count in duplicate_accounts:
        issues.append(
            f"duplicate account_number {account_number!r} appears in {count} attendance source rows"
        )

    staged_accounts = connection.execute(
        select(StagingAttendanceStudent.account_number).where(
            StagingAttendanceStudent.source_system == SOURCE_SYSTEM
        )
    ).scalars().all()
    for account_number in staged_accounts:
        match_count = connection.execute(
            select(func.count())
            .select_from(Student)
            .where(Student.account_number == account_number)
        ).scalar_one()
        issue = _reconciliation_issue(account_number, match_count)
        if issue:
            issues.append(issue)

    student_source_ids = set(
        connection.execute(
            select(StagingAttendanceStudent.source_id).where(
                StagingAttendanceStudent.source_system == SOURCE_SYSTEM
            )
        ).scalars()
    )
    session_source_ids = set(
        connection.execute(
            select(StagingAttendanceSession.source_id).where(
                StagingAttendanceSession.source_system == SOURCE_SYSTEM
            )
        ).scalars()
    )

    records = connection.execute(
        select(
            StagingAttendanceRecord.source_id,
            StagingAttendanceRecord.student_source_id,
            StagingAttendanceRecord.session_source_id,
        ).where(StagingAttendanceRecord.source_system == SOURCE_SYSTEM)
    ).all()
    for source_id, student_source_id, session_source_id in records:
        if student_source_id not in student_source_ids:
            issues.append(
                f"attendance record source_id={source_id!r} references unknown "
                f"student_source_id={student_source_id!r}"
            )
        if session_source_id not in session_source_ids:
            issues.append(
                f"attendance record source_id={source_id!r} references unknown "
                f"session_source_id={session_source_id!r}"
            )

    duplicate_pairs = connection.execute(
        select(
            StagingAttendanceRecord.student_source_id,
            StagingAttendanceRecord.session_source_id,
            func.count().label("n"),
        )
        .where(StagingAttendanceRecord.source_system == SOURCE_SYSTEM)
        .group_by(
            StagingAttendanceRecord.student_source_id, StagingAttendanceRecord.session_source_id
        )
        .having(func.count() > 1)
    ).all()
    for student_source_id, session_source_id, count in duplicate_pairs:
        issues.append(
            f"duplicate attendance for student_source_id={student_source_id!r} "
            f"session_source_id={session_source_id!r} ({count} source rows)"
        )

    return issues
