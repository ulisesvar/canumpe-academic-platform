"""Builds staging.* from one batch's extracted rows.

Staging is fully rebuilt for this source_system on every run (existing
`source_system='moodle'` rows are deleted first) — see the README's
staging lifecycle section. Only structurally well-formed rows (required
fields present and non-empty) are written; anything else is reported as
an issue instead and simply left out of staging. This function does not
decide whether the batch as a whole may proceed to merge — that is
`validate_staged_batch`'s job, reading staging back.
"""

import uuid

from sqlalchemy import delete, insert
from sqlalchemy.engine import Connection

from app.integration.moodle.hashing import course_hash, enrollment_hash, student_hash
from app.integration.moodle.models.staging import (
    StagingCourse,
    StagingEnrollment,
    StagingStudent,
)
from app.integration.moodle.source import MoodleExtractionResult

SOURCE_SYSTEM = "moodle"


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def write_staging_batch(
    connection: Connection, batch_id: uuid.UUID, extraction: MoodleExtractionResult
) -> list[str]:
    issues: list[str] = []

    connection.execute(delete(StagingStudent).where(StagingStudent.source_system == SOURCE_SYSTEM))
    connection.execute(delete(StagingCourse).where(StagingCourse.source_system == SOURCE_SYSTEM))
    connection.execute(
        delete(StagingEnrollment).where(StagingEnrollment.source_system == SOURCE_SYSTEM)
    )

    student_rows = []
    for s in extraction.students:
        account_number = _clean_text(s.account_number)
        if not account_number:
            issues.append(f"student source_id={s.source_id!r} is missing account_number")
            continue
        student_rows.append(
            {
                "batch_id": batch_id,
                "source_system": SOURCE_SYSTEM,
                "source_id": s.source_id,
                "account_number": account_number,
                "first_name": _clean_text(s.first_name) or "",
                "last_name": _clean_text(s.last_name) or "",
                "email": _clean_text(s.email),
                "source_updated_at": s.source_updated_at,
                "source_hash": student_hash(s.account_number, s.first_name, s.last_name, s.email),
            }
        )
    if student_rows:
        connection.execute(insert(StagingStudent), student_rows)

    course_rows = []
    for c in extraction.courses:
        name = _clean_text(c.name)
        if not name:
            issues.append(f"course source_id={c.source_id!r} is missing name")
            continue
        course_rows.append(
            {
                "batch_id": batch_id,
                "source_system": SOURCE_SYSTEM,
                "source_id": c.source_id,
                "code": _clean_text(c.code),
                "name": name,
                "active": c.visible,
                "source_updated_at": c.source_updated_at,
                "source_hash": course_hash(c.code, c.name, c.visible),
            }
        )
    if course_rows:
        connection.execute(insert(StagingCourse), course_rows)

    enrollment_rows = [
        {
            "batch_id": batch_id,
            "source_system": SOURCE_SYSTEM,
            "source_id": e.source_id,
            "student_source_id": e.student_source_id,
            "course_source_id": e.course_source_id,
            "status": e.status,
            "source_updated_at": e.source_updated_at,
            "source_hash": enrollment_hash(e.student_source_id, e.course_source_id, e.status),
        }
        for e in extraction.enrollments
    ]
    if enrollment_rows:
        connection.execute(insert(StagingEnrollment), enrollment_rows)

    return issues
