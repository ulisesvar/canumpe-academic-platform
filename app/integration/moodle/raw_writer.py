"""Writes one batch's extracted rows into raw_moodle.* — a faithful,
append-only landing copy. RAW is never validated and never truncated by
a sync run; see the README's RAW retention section.
"""

import uuid

from sqlalchemy import insert
from sqlalchemy.engine import Connection

from app.integration.moodle.hashing import course_hash, enrollment_hash, student_hash
from app.integration.moodle.models.raw import (
    RawMoodleCourse,
    RawMoodleEnrollment,
    RawMoodleStudent,
)
from app.integration.moodle.source import MoodleExtractionResult


def write_raw_batch(
    connection: Connection, batch_id: uuid.UUID, extraction: MoodleExtractionResult
) -> None:
    if extraction.students:
        connection.execute(
            insert(RawMoodleStudent),
            [
                {
                    "batch_id": batch_id,
                    "source_id": s.source_id,
                    "account_number": s.account_number,
                    "first_name": s.first_name,
                    "last_name": s.last_name,
                    "email": s.email,
                    "source_updated_at": s.source_updated_at,
                    "source_hash": student_hash(
                        s.account_number, s.first_name, s.last_name, s.email
                    ),
                }
                for s in extraction.students
            ],
        )

    if extraction.courses:
        connection.execute(
            insert(RawMoodleCourse),
            [
                {
                    "batch_id": batch_id,
                    "source_id": c.source_id,
                    "code": c.code,
                    "name": c.name,
                    "visible": c.visible,
                    "source_updated_at": c.source_updated_at,
                    "source_hash": course_hash(c.code, c.name, c.visible),
                }
                for c in extraction.courses
            ],
        )

    if extraction.enrollments:
        connection.execute(
            insert(RawMoodleEnrollment),
            [
                {
                    "batch_id": batch_id,
                    "source_id": e.source_id,
                    "student_source_id": e.student_source_id,
                    "course_source_id": e.course_source_id,
                    "status": e.status,
                    "source_updated_at": e.source_updated_at,
                    "source_hash": enrollment_hash(
                        e.student_source_id, e.course_source_id, e.status
                    ),
                }
                for e in extraction.enrollments
            ],
        )
