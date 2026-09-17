"""Deterministic content hashing for Moodle grade source rows.

Same approach and normalization rules as app.integration.moodle.hashing:
SHA-256 over business-relevant fields only, joined with a 0x1f separator.
Never batch_id/ingested_at/source_updated_at — Moodle's own modification
timestamp is bookkeeping, not content, exactly like every other hash in
this platform. "source identity" (per the README) means the *foreign*
identity a row belongs to (its course, or its grade item + student) —
never the row's own source_id, which is the dedup key these hashes are
compared alongside, not hashed content.
"""

from app.integration.moodle.hashing import hash_fields


def grade_item_hash(
    course_source_id: object, name: object, itemmodule: object, max_grade: object, hidden: object
) -> str:
    return hash_fields(course_source_id, name, itemmodule, max_grade, hidden)


def student_grade_hash(
    grade_item_source_id: object, student_source_id: object, grade: object, hidden: object
) -> str:
    return hash_fields(grade_item_source_id, student_source_id, grade, hidden)
