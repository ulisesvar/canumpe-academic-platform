"""API key generation, hashing, and persistence.

Plaintext keys are never stored: only SHA-256(plaintext) (key_hash) and
a short, non-secret prefix (key_prefix — enough to recognize a
credential in a listing, never enough to reconstruct the secret) ever
reach the database. A plaintext key is returned to the caller exactly
once, at generation time — see app.auth.manage_api_keys, the only
caller that ever prints one. This module never logs a plaintext key.

Every write here is transactional as a whole: rotate_student_key revokes
the previous key(s) and inserts the new one in the same commit, so a
failure partway through leaves the previous key intact rather than
locking a student out.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.academic.models import Student
from app.auth.models import ROLE_ADMIN, ROLE_STUDENT, ApiKey

STUDENT_KEY_PREFIX = "canumpe_stu_"
ADMIN_KEY_PREFIX = "canumpe_adm_"

#: Characters of the plaintext kept as the stored, non-secret key_prefix.
#: The role prefix (12 chars) plus a handful of the random secret is
#: enough to recognize a credential in a listing; the remaining ~250
#: bits of secrets.token_urlsafe(32) entropy stay hidden.
DISPLAY_PREFIX_LENGTH = 16


class StudentNotFoundError(Exception):
    """Raised when an account_number does not resolve to a canonical student."""

    def __init__(self, account_number: str) -> None:
        self.account_number = account_number
        super().__init__(f"no student with account_number={account_number!r}")


class ActiveStudentKeyExistsError(Exception):
    """Raised by issue_student_key when the student already has an
    active key — rotate_student_key is the supported way to replace one.
    """

    def __init__(self, student_id: int) -> None:
        self.student_id = student_id
        super().__init__(f"student_id={student_id!r} already has an active API key")


@dataclass(frozen=True)
class KeyMaterial:
    """A freshly generated key, not yet persisted anywhere."""

    plaintext: str
    key_hash: str
    key_prefix: str


@dataclass(frozen=True)
class GeneratedKey:
    """A key that has been persisted — KeyMaterial plus its row id."""

    id: int
    plaintext: str
    key_hash: str
    key_prefix: str


@dataclass(frozen=True)
class ApiKeySummary:
    id: int
    key_prefix: str
    role: str
    student_id: int | None
    account_number: str | None
    label: str | None
    created_at: datetime
    revoked_at: datetime | None


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _generate_key_material(prefix: str) -> KeyMaterial:
    """256 bits of cryptographically secure randomness — never
    random/uuid/timestamps/account numbers/Telegram or student ids.
    Pure and DB-free, so key generation itself is testable in isolation
    from persistence.
    """
    plaintext = f"{prefix}{secrets.token_urlsafe(32)}"
    return KeyMaterial(
        plaintext=plaintext,
        key_hash=hash_key(plaintext),
        key_prefix=plaintext[:DISPLAY_PREFIX_LENGTH],
    )


def generate_student_key() -> KeyMaterial:
    return _generate_key_material(STUDENT_KEY_PREFIX)


def generate_admin_key() -> KeyMaterial:
    return _generate_key_material(ADMIN_KEY_PREFIX)


def _resolve_student_id(db: Session, account_number: str) -> int:
    student_id = db.execute(
        select(Student.id).where(Student.account_number == account_number)
    ).scalar_one_or_none()
    if student_id is None:
        raise StudentNotFoundError(account_number)
    return student_id


def _has_active_student_key(db: Session, student_id: int) -> bool:
    return (
        db.execute(
            select(ApiKey.id).where(
                ApiKey.student_id == student_id,
                ApiKey.role == ROLE_STUDENT,
                ApiKey.revoked_at.is_(None),
            )
        ).scalar_one_or_none()
        is not None
    )


def _insert_key(
    db: Session, *, material: KeyMaterial, role: str, student_id: int | None, label: str | None
) -> GeneratedKey:
    new_id = db.execute(
        insert(ApiKey)
        .values(
            key_hash=material.key_hash,
            key_prefix=material.key_prefix,
            role=role,
            student_id=student_id,
            label=label,
        )
        .returning(ApiKey.id)
    ).scalar_one()
    return GeneratedKey(
        id=new_id,
        plaintext=material.plaintext,
        key_hash=material.key_hash,
        key_prefix=material.key_prefix,
    )


def issue_student_key(
    db: Session, *, account_number: str, label: str | None = None
) -> GeneratedKey:
    """Issues one active student key. Fails if the account number
    doesn't resolve, or if the student already has an active key —
    both checked up front, and the active-key rule also enforced by the
    database's partial unique index (uq_api_keys_active_student) as a
    second line of defense against a concurrent issue.
    """
    student_id = _resolve_student_id(db, account_number)
    if _has_active_student_key(db, student_id):
        raise ActiveStudentKeyExistsError(student_id)

    try:
        generated = _insert_key(
            db,
            material=generate_student_key(),
            role=ROLE_STUDENT,
            student_id=student_id,
            label=label,
        )
    except IntegrityError as exc:
        db.rollback()
        raise ActiveStudentKeyExistsError(student_id) from exc

    db.commit()
    return generated


def issue_admin_key(db: Session, *, label: str | None = None) -> GeneratedKey:
    """Admin keys have no student_id and may coexist — different admin
    clients may eventually each hold their own.
    """
    generated = _insert_key(
        db, material=generate_admin_key(), role=ROLE_ADMIN, student_id=None, label=label
    )
    db.commit()
    return generated


def rotate_student_key(
    db: Session, *, account_number: str, label: str | None = None, now: datetime | None = None
) -> GeneratedKey:
    """Revokes every currently-active student key for this student and
    issues one new one, atomically: both happen in the same
    transaction, so a failure partway through leaves the previous key
    active rather than locking the student out.
    """
    effective_now = now or datetime.now(UTC)
    student_id = _resolve_student_id(db, account_number)

    db.execute(
        update(ApiKey)
        .where(
            ApiKey.student_id == student_id,
            ApiKey.role == ROLE_STUDENT,
            ApiKey.revoked_at.is_(None),
        )
        .values(revoked_at=effective_now)
    )
    generated = _insert_key(
        db, material=generate_student_key(), role=ROLE_STUDENT, student_id=student_id, label=label
    )
    db.commit()
    return generated


def revoke_key(db: Session, *, api_key_id: int, now: datetime | None = None) -> None:
    """A no-op if the key doesn't exist or is already revoked — never
    deletes the row, so credential history is retained permanently.
    """
    effective_now = now or datetime.now(UTC)
    db.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key_id, ApiKey.revoked_at.is_(None))
        .values(revoked_at=effective_now)
    )
    db.commit()


def get_active_key_by_hash(db: Session, key_hash: str) -> ApiKey | None:
    """Read-only lookup used by the authentication dependency on every
    request — never writes, never updates a last-used timestamp.
    """
    return db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
    ).scalar_one_or_none()


def list_keys(db: Session) -> list[ApiKeySummary]:
    """Safe metadata only — never plaintext, never the full key_hash."""
    stmt = (
        select(
            ApiKey.id,
            ApiKey.key_prefix,
            ApiKey.role,
            ApiKey.student_id,
            Student.account_number,
            ApiKey.label,
            ApiKey.created_at,
            ApiKey.revoked_at,
        )
        .select_from(ApiKey)
        .outerjoin(Student, Student.id == ApiKey.student_id)
        .order_by(ApiKey.id)
    )
    return [ApiKeySummary(**row._mapping) for row in db.execute(stmt).all()]
