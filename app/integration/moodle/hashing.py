"""Deterministic content hashing for Moodle source rows.

`source_hash` exists to answer one question cheaply during a merge:
"did anything about this record actually change?" It is computed from
business-relevant fields only — never batch_id or ingested_at, since
those change on every run regardless of content, which would make the
hash useless for change detection. source_updated_at is also excluded:
Moodle's own modification timestamp is bookkeeping, not content, and
excluding it keeps the hash's meaning independent of Moodle's internals.

Normalization is deliberately simple and documented so the same source
content always produces the same hash:
- None becomes an empty string
- booleans become the literal strings "true"/"false"
- everything else is str()-ed and stripped of leading/trailing whitespace
Fields are joined with a control character (0x1f, ASCII "unit separator")
that cannot appear in normal text input, so distinct field combinations
cannot collide by concatenation (e.g. ("ab", "c") vs ("a", "bc")).
"""

import hashlib

_FIELD_SEPARATOR = "\x1f"


def _normalize(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def hash_fields(*values: object) -> str:
    """SHA-256 hex digest of the given values, normalized and joined."""
    normalized = _FIELD_SEPARATOR.join(_normalize(value) for value in values)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def student_hash(
    account_number: object, first_name: object, last_name: object, email: object
) -> str:
    return hash_fields(account_number, first_name, last_name, email)


def course_hash(code: object, name: object, visible: object) -> str:
    return hash_fields(code, name, visible)


def enrollment_hash(student_source_id: object, course_source_id: object, status: object) -> str:
    return hash_fields(student_source_id, course_source_id, status)
