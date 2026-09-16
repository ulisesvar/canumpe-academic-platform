"""Deterministic content hashing for Attendance source rows.

Same approach and normalization rules as app.integration.moodle.hashing:
SHA-256 over business-relevant fields only, joined with a 0x1f separator
so distinct field combinations can't collide by concatenation. Never
batch_id/ingested_at. Coordinates/distance/telegram data are excluded
because they are never ingested at all — see the README's minimal-data
principle.
"""

from app.integration.moodle.hashing import hash_fields


def attendance_student_hash(account_number: object) -> str:
    return hash_fields(account_number)


def attendance_session_hash(opened_at: object, closed_at: object, status: object) -> str:
    return hash_fields(opened_at, closed_at, status)


def attendance_record_hash(
    student_source_id: object, session_source_id: object, recorded_at: object
) -> str:
    return hash_fields(student_source_id, session_source_id, recorded_at)
